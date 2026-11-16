"""Phase 9 (optional) — QLoRA fine-tune of a small code model.

Pitch: a 3B model on free infrastructure (Colab T4 / Kaggle) that approaches a frontier
model's precision on this narrow task. Only worth doing once Phases 1-8 are solid.

Base model: Qwen2.5-Coder-1.5B-Instruct or -3B-Instruct (code-specialized, small
enough for a free T4 with 4-bit QLoRA: r=16, alpha=32, 3 epochs, batch 2 with gradient
accumulation).

Evaluate the result on the SAME benchmark and add it as another row in the ablation
table. If it underperforms the API model, say so, and say what would close the gap. A
negative result honestly reported reads better than an unverified claim.

This script imports heavy deps lazily so the rest of the repo installs without them:
    pip install -e ".[finetune]"
"""

from __future__ import annotations

import argparse


def train(
    data_path: str,
    base_model: str = "Qwen/Qwen2.5-Coder-1.5B-Instruct",
    out_dir: str = "finetune/checkpoints/prlens-lora",
    epochs: int = 3,
    batch_size: int = 2,
    grad_accum: int = 8,
    lr: float = 2e-4,
):
    import torch
    from datasets import load_dataset
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
    )
    from trl import SFTConfig, SFTTrainer

    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
    )

    tok = AutoTokenizer.from_pretrained(base_model)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        base_model, quantization_config=bnb, device_map="auto"
    )
    model = prepare_model_for_kbit_training(model)

    lora = LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
    )
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    ds = load_dataset("json", data_files=data_path, split="train")

    def format_example(ex):
        return {"text": tok.apply_chat_template(ex["messages"], tokenize=False)}

    ds = ds.map(format_example, remove_columns=ds.column_names)

    cfg = SFTConfig(
        output_dir=out_dir,
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=grad_accum,
        learning_rate=lr,
        logging_steps=10,
        save_strategy="epoch",
        bf16=False,
        fp16=True,
        max_seq_length=2048,
        report_to="none",
    )
    trainer = SFTTrainer(model=model, train_dataset=ds, args=cfg, tokenizer=tok)
    trainer.train()
    trainer.save_model(out_dir)
    print(f"Saved LoRA adapter to {out_dir}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="QLoRA fine-tune on the SFT dataset")
    ap.add_argument("--data", default="finetune/sft.jsonl")
    ap.add_argument("--base-model", default="Qwen/Qwen2.5-Coder-1.5B-Instruct")
    ap.add_argument("--out", default="finetune/checkpoints/prlens-lora")
    ap.add_argument("--epochs", type=int, default=3)
    args = ap.parse_args(argv)
    try:
        train(args.data, args.base_model, args.out, epochs=args.epochs)
    except ImportError as e:
        print(
            "Fine-tuning dependencies are not installed. Run `pip install -e "
            f'".[finetune]"` on a machine with a GPU.\nMissing: {e}'
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
