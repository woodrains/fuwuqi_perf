import yaml
from datasets import load_dataset
from peft import LoraConfig
from transformers import AutoModelForCausalLM, AutoTokenizer
from trl import DPOTrainer, DPOConfig
from src.utils.path_resolver import get_base_model_path


def main(cfg_path="configs/paths.yaml", epochs=1, data_path="./data/llmevaluator/data_dpo.json"):
    cfg = yaml.safe_load(open(cfg_path))
    model_name = get_base_model_path(cfg)
    out_dir = cfg["models"]["dpo_out_dir"]

    tokenizer = AutoTokenizer.from_pretrained(model_name)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(model_name, device_map="auto")

    lora_config = LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "v_proj"],
    )

    dataset = load_dataset("json", data_files=data_path, split="train")

    training_args = DPOConfig(
        output_dir=out_dir,
        per_device_train_batch_size=4,
        gradient_accumulation_steps=4,
        num_train_epochs=epochs,
        learning_rate=1e-5,
        save_steps=100,
        logging_steps=10,
        remove_unused_columns=False,
    )

    trainer = DPOTrainer(
        model=model,
        ref_model=None,
        args=training_args,
        train_dataset=dataset,
        tokenizer=tokenizer,
        peft_config=lora_config,
    )
    trainer.train()
    trainer.save_model(out_dir)
    print(f"DPO model saved to {out_dir}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--cfg", default="configs/paths.yaml")
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--data_path", default="./data/llmevaluator/data_dpo.json")
    args = ap.parse_args()
    main(cfg_path=args.cfg, epochs=args.epochs, data_path=args.data_path)
