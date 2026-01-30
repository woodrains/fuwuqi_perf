import re
import json
import yaml
import torch
import random
import argparse
from statistics import median
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel
from src.utils.path_resolver import get_base_model_path


def extract_number(text: str):
    m = re.search(r"Profile:\s*([0-9]+(?:\.[0-9]+)?)", text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


@torch.no_grad()
def predict_k(model, tokenizer, prompt: str, k=5, max_new_tokens=6):
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    preds = []
    for _ in range(k):
        out = model.generate(
            **inputs,
            do_sample=True,
            top_p=0.95,
            temperature=0.8,
            max_new_tokens=max_new_tokens,
        )
        txt = tokenizer.decode(out[0], skip_special_tokens=True)
        preds.append(extract_number(txt))
    return preds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cfg", default="configs/paths.yaml")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--peft_model", default="")
    args = ap.parse_args()

    cfg = yaml.safe_load(open(args.cfg))
    model_name = get_base_model_path(cfg)
    use_bf16 = bool(cfg["llm"].get("use_bf16", True))
    test_json = cfg["data"]["llm_test_profile"]

    tok = AutoTokenizer.from_pretrained(model_name)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(model_name, torch_dtype=(torch.bfloat16 if use_bf16 else None), device_map="auto")
    if args.peft_model:
        model = PeftModel.from_pretrained(model, args.peft_model)
    model.eval()

    data = json.load(open(test_json))

    total = 0
    mape_sum = 0.0
    pass5_hits = 0

    for ex in data:
        prompt = ex["instruction"] + "\nProfile: "
        gt = extract_number(ex.get("output", ""))
        if gt is None or gt == 0:
            continue
        preds = predict_k(model, tok, prompt, k=args.k)
        preds_valid = [p for p in preds if p is not None]
        if not preds_valid:
            continue

        med_pred = median(preds_valid)
        mape = abs(med_pred - gt) / abs(gt)
        mape_sum += mape
        total += 1

        # pass@5 success: any prediction within 10% relative error
        if any(abs(p - gt) / abs(gt) <= 0.1 for p in preds_valid):
            pass5_hits += 1

    mape_avg = (mape_sum / total) if total else 0.0
    pass5_acc = (pass5_hits / total) if total else 0.0

    print(f"Samples evaluated: {total}")
    print(f"MAPE (median-of-{args.k}): {mape_avg:.6f}")
    print(f"pass@{args.k} within 10%: {pass5_acc*100:.2f}%")


if __name__ == "__main__":
    main()
