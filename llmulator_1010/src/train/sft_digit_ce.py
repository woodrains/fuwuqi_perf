# -*- coding: utf-8 -*-
"""
LoRA SFT for numeric tokenization (first-digit cross-entropy) with pass@5 evaluation.
Copied/adapted from ../llmulator/sfttrain.py without changing the core modeling idea.
"""

import yaml
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader
from torch.utils.tensorboard import SummaryWriter
from transformers import AutoTokenizer, AutoModelForCausalLM, GenerationConfig
from peft import LoraConfig, get_peft_model
from src.data.json_dataset import JsonDataset
from src.utils.path_resolver import get_base_model_path

device = "cuda"
DIGITS = [str(i) for i in range(10)]


def float_to_digit_label(x: torch.Tensor) -> torch.Tensor:
    return torch.round(x * 9).clamp(0, 9).long()


def build_lora_causal_lm(model_name: str):
    base = AutoModelForCausalLM.from_pretrained(model_name, device_map="auto")
    lora_cfg = LoraConfig(
        task_type="CAUSAL_LM",
        r=8,
        lora_alpha=32,
        lora_dropout=0.05,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
    )
    model = get_peft_model(base, lora_cfg)
    return model


class TextDigitModel(nn.Module):
    def __init__(self, model_name: str):
        super().__init__()
        self.lm = build_lora_causal_lm(model_name)
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token

        digit_ids = [self.tokenizer.encode(d, add_special_tokens=False)[0] for d in DIGITS]
        self.register_buffer("digit_token_ids", torch.tensor(digit_ids, dtype=torch.long))

    def forward(self, input_ids, attention_mask=None, labels=None):
        out = self.lm(
            input_ids=input_ids,
            attention_mask=attention_mask,
            use_cache=False,
            return_dict=True,
        )
        last_logits = out.logits[:, -1, :]
        loss = None
        if labels is not None:
            gold_tids = self.digit_token_ids[labels]
            loss = F.cross_entropy(last_logits, gold_tids)

        preds_tid = last_logits.argmax(dim=-1)
        preds_txt = self.tokenizer.batch_decode(preds_tid, skip_special_tokens=True)
        preds_digit = [t[0] if t else "?" for t in preds_txt]
        return loss, preds_digit

    @torch.no_grad()
    def generate_digits(self, prompt_ids, max_new_tokens=4, do_sample=False, top_p=0.9, temperature=0.7):
        gen_cfg = GenerationConfig(
            do_sample=do_sample,
            top_p=top_p,
            temperature=temperature,
            max_new_tokens=max_new_tokens,
            pad_token_id=self.tokenizer.eos_token_id,
            eos_token_id=self.tokenizer.eos_token_id,
        )
        out_ids = self.lm.generate(prompt_ids, generation_config=gen_cfg)
        gen_part = out_ids[:, prompt_ids.size(1) :]
        return self.tokenizer.batch_decode(gen_part, skip_special_tokens=True)[0]


@torch.no_grad()
def evaluate_pass5(model, tokenizer, test_dl, writer, global_step, max_len=128):
    model.eval()
    total, success = 0, 0
    for batch in test_dl:
        (
            _,
            _,
            _,
            _,
            _,
            _,
            _,
            profile_value,
            inputs,
            *_,
        ) = batch
        profile_value = profile_value.to(device).float()
        enc = tokenizer(
            [str(x) for x in inputs],
            return_tensors="pt",
            truncation=True,
            max_length=max_len,
        ).to(device)

        # pass@5: sample 5 generations; success if any matches first digit label
        gold_digit = int(float_to_digit_label(profile_value))
        ok = False
        for _ in range(5):
            gen_text = model.generate_digits(enc["input_ids"], max_new_tokens=4, do_sample=True, top_p=0.95, temperature=0.8)
            pred_digit = gen_text[0] if gen_text and gen_text[0].isdigit() else "?"
            if pred_digit.isdigit() and int(pred_digit) == gold_digit:
                ok = True
                break
        total += 1
        success += int(ok)

    pass_at_5 = success / total if total else 0.0
    print(f"[Eval] pass@5 (first-digit) = {pass_at_5*100:.2f}%")
    writer.add_scalar("eval/pass5_first_digit", pass_at_5, global_step)
    model.train()


def train_with_ce(cfg_path="configs/paths.yaml", epochs=5, lr=1e-4, max_len=128):
    cfg = yaml.safe_load(open(cfg_path))
    model_name = get_base_model_path(cfg)
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = TextDigitModel(model_name).to(device)
    train_dl = DataLoader(JsonDataset(cfg["data"]["train_dir"]), batch_size=1, shuffle=True)
    test_dl = DataLoader(JsonDataset(cfg["data"]["test_dir"]), batch_size=1, shuffle=False)

    opt = torch.optim.AdamW(filter(lambda p: p.requires_grad, model.parameters()), lr=lr)
    writer = SummaryWriter("logs_ce")
    global_step = 0

    for epoch in range(epochs):
        model.train()
        for batch_idx, batch in enumerate(train_dl):
            (
                _,
                _,
                _,
                _,
                _,
                _,
                _,
                profile_value,
                inputs,
                *_,
            ) = batch
            profile_value = profile_value.to(device).float()
            enc = tokenizer(
                [str(x) for x in inputs],
                padding=True,
                return_tensors="pt",
                truncation=True,
                max_length=max_len,
            ).to(device)

            labels = float_to_digit_label(profile_value).to(device)
            loss, preds_digit = model(
                input_ids=enc["input_ids"], attention_mask=enc["attention_mask"], labels=labels
            )
            opt.zero_grad()
            loss.backward()
            opt.step()

            if global_step % 50 == 0:
                print(
                    f"[CE] epoch {epoch} step {global_step}  loss {loss.item():.4f}  pred {preds_digit}  gold {labels.tolist()}"
                )
                writer.add_scalar("train/loss_ce", loss.item(), global_step)
            global_step += 1

        evaluate_pass5(model, tokenizer, test_dl, writer, global_step, max_len)

    # Save PEFT adapter
    out_dir = cfg["models"]["sft_out_dir"]
    import os
    os.makedirs(out_dir, exist_ok=True)
    model.lm.save_pretrained(out_dir)
    print(f"✅ SFT training done. LoRA saved to {out_dir}")


if __name__ == "__main__":
    train_with_ce(epochs=5)
