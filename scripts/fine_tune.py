"""
Fine-tune TinyLlama-1.1B-Chat on ChatGenius knowledge base using LoRA (PEFT).
Optimized for macOS (MPS/CPU). No paid APIs needed.
"""

import json
import os
import sys
import torch
from datasets import Dataset
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    TrainingArguments,
    Trainer,
    DataCollatorForLanguageModeling,
)
from peft import LoraConfig, get_peft_model, TaskType

# ── Config ──
BASE_MODEL = "TinyLlama/TinyLlama-1.1B-Chat-v1.0"
DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "training_data.jsonl")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "models", "chatgenius-tinyllama")
MAX_LENGTH = 512

# Detect device
if torch.backends.mps.is_available():
    DEVICE = "mps"
    print("Using Apple Silicon MPS acceleration")
elif torch.cuda.is_available():
    DEVICE = "cuda"
    print("Using CUDA GPU")
else:
    DEVICE = "cpu"
    print("Using CPU (this will be slower)")


def load_data():
    """Load training data from JSONL."""
    texts = []
    with open(DATA_PATH, "r") as f:
        for line in f:
            item = json.loads(line.strip())
            texts.append(item["text"])
    print(f"Loaded {len(texts)} training examples")
    return texts


def tokenize_data(texts, tokenizer):
    """Tokenize all training texts."""
    dataset = Dataset.from_dict({"text": texts})

    def tokenize_fn(examples):
        tokenized = tokenizer(
            examples["text"],
            truncation=True,
            max_length=MAX_LENGTH,
            padding="max_length",
        )
        tokenized["labels"] = tokenized["input_ids"].copy()
        return tokenized

    tokenized = dataset.map(tokenize_fn, batched=True, remove_columns=["text"])
    return tokenized


def main():
    print(f"\n{'='*60}")
    print(f"  ChatGenius Fine-Tuning Pipeline")
    print(f"  Base Model: {BASE_MODEL}")
    print(f"  Device: {DEVICE}")
    print(f"{'='*60}\n")

    # Step 1: Load tokenizer and model
    print("[1/5] Loading tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    print("[2/5] Loading base model...")
    # Load in float32 for MPS/CPU compatibility
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        dtype=torch.float32,
        device_map=None,  # We'll handle device placement manually
    )

    # Step 2: Configure LoRA
    print("[3/5] Applying LoRA adapters...")
    lora_config = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=16,                    # LoRA rank
        lora_alpha=32,           # LoRA scaling
        lora_dropout=0.05,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
        bias="none",
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # Step 3: Load and tokenize data
    print("[4/5] Preparing training data...")
    texts = load_data()
    train_dataset = tokenize_data(texts, tokenizer)

    # Data collator
    data_collator = DataCollatorForLanguageModeling(
        tokenizer=tokenizer,
        mlm=False,
    )

    # Step 4: Training
    print("[5/5] Starting fine-tuning...\n")

    # Use CPU for training if MPS causes issues with Trainer
    use_cpu = DEVICE in ("mps", "cpu")

    training_args = TrainingArguments(
        output_dir=OUTPUT_DIR,
        num_train_epochs=6,
        per_device_train_batch_size=2,
        gradient_accumulation_steps=4,
        learning_rate=2e-4,
        weight_decay=0.01,
        warmup_steps=10,
        logging_steps=5,
        save_steps=50,
        save_total_limit=2,
        fp16=False,
        bf16=False,
        use_cpu=use_cpu,
        dataloader_pin_memory=False,
        report_to="none",
        lr_scheduler_type="cosine",
        optim="adamw_torch",
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        data_collator=data_collator,
    )

    # Train
    print("Training started...")
    train_result = trainer.train()

    # Save
    print(f"\nSaving fine-tuned model to {OUTPUT_DIR}...")
    trainer.save_model(OUTPUT_DIR)
    tokenizer.save_pretrained(OUTPUT_DIR)

    # Save training metrics
    metrics = train_result.metrics
    metrics_path = os.path.join(OUTPUT_DIR, "training_metrics.json")
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2)

    print(f"\n{'='*60}")
    print(f"  Fine-tuning complete!")
    print(f"  Training loss: {metrics.get('train_loss', 'N/A'):.4f}")
    print(f"  Model saved to: {OUTPUT_DIR}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
