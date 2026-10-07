#!/usr/bin/env python3
"""
PROJECT SHADOW — Neural Network Training Script
=================================================

Trains a 1D Convolutional Neural Network (CSINet) to classify motion states
from raw Wi-Fi CSI data. This is the "neural" component of the
Wi-Fi Interferometric Neural Sensing system.

Usage:
    1. Record raw CSI data using radar_graph.py:
       python radar_graph.py --port COM8 --record empty --raw-log raw_empty.csv
       python radar_graph.py --port COM8 --record walking --raw-log raw_walking.csv
       python radar_graph.py --port COM8 --record weapon --raw-log raw_weapon.csv

    2. Train the model:
       python train_model.py --data raw_empty.csv raw_walking.csv
       python train_model.py --data raw_empty.csv raw_walking.csv raw_weapon.csv

    3. Use the model in real-time:
       python radar_graph.py --port COM8 --ai

Output:
    - shadow_neural_model.pt  (PyTorch model + metadata)
    - training_results.json   (accuracy, loss, confusion matrix)

Author: PROJECT SHADOW
"""

import argparse
import json
import os
import sys
import time
import numpy as np
import pandas as pd
from pathlib import Path

# ── PyTorch ───────────────────────────────────────────────────────────────
try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    from torch.utils.data import Dataset, DataLoader, random_split
except ImportError:
    print("ERROR: PyTorch is required. Install with:")
    print("  pip install torch")
    sys.exit(1)

# ── Scikit-learn for evaluation ───────────────────────────────────────────
try:
    from sklearn.metrics import (
        classification_report, confusion_matrix,
        accuracy_score, f1_score
    )
except ImportError:
    print("ERROR: scikit-learn is required. Install with:")
    print("  pip install scikit-learn")
    sys.exit(1)

# ── Matplotlib for plots ─────────────────────────────────────────────────
try:
    import matplotlib
    matplotlib.use("TkAgg")
    import matplotlib.pyplot as plt
except ImportError:
    plt = None


# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

NORMALIZED_SUBCARRIER_COUNT = 52   # Must match radar_graph.py
WINDOW_SIZE = 20                    # Number of consecutive packets per sample
STRIDE = 5                          # Slide window by this many packets
BATCH_SIZE = 32
LEARNING_RATE = 0.001
NUM_EPOCHS = 50
TRAIN_SPLIT = 0.8                   # 80% train, 20% test
RANDOM_SEED = 42

# Data augmentation parameters
AUGMENT_NOISE_STD = 0.05           # Gaussian noise standard deviation (relative)
AUGMENT_TIME_SHIFT_MAX = 3         # Max packets to shift in time
AUGMENT_SCALE_RANGE = (0.9, 1.1)   # Amplitude scaling range
AUGMENT_COPIES = 3                 # Number of augmented copies per original sample


# ═══════════════════════════════════════════════════════════════════════════
# NEURAL NETWORK MODEL (must match radar_graph.py)
# ═══════════════════════════════════════════════════════════════════════════

class CSINet(nn.Module):
    """
    1D Convolutional Neural Network for CSI-based motion classification.
    Input: (batch, 1, WINDOW_SIZE * NORMALIZED_SUBCARRIER_COUNT * 2)
    Output: (batch, num_classes)
    """
    def __init__(self, input_size, num_classes=2):
        super(CSINet, self).__init__()
        self.features = nn.Sequential(
            nn.Conv1d(1, 32, kernel_size=7, padding=3),
            nn.BatchNorm1d(32),
            nn.ReLU(),
            nn.MaxPool1d(2),

            nn.Conv1d(32, 64, kernel_size=5, padding=2),
            nn.BatchNorm1d(64),
            nn.ReLU(),
            nn.MaxPool1d(2),

            nn.Conv1d(64, 128, kernel_size=3, padding=1),
            nn.BatchNorm1d(128),
            nn.ReLU(),
            nn.AdaptiveAvgPool1d(8),
        )
        self.classifier = nn.Sequential(
            nn.Flatten(),
            nn.Linear(128 * 8, 64),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(64, num_classes),
        )

    def forward(self, x):
        x = self.features(x)
        x = self.classifier(x)
        return x


# ═══════════════════════════════════════════════════════════════════════════
# DATASET
# ═══════════════════════════════════════════════════════════════════════════

class CSIDataset(Dataset):
    """
    Loads raw CSI CSV files and creates sliding-window samples.
    Each sample is a flattened vector of (WINDOW_SIZE × subcarriers × 2)
    containing both amplitude and phase data.

    If use_differential=True, also appends temporal difference features
    (amp[i]-amp[i-1], phase[i]-phase[i-1]) which are more robust to
    environment/placement changes.
    """

    def __init__(self, csv_files: list, label_map: dict = None, use_differential: bool = False):
        """
        Args:
            csv_files: List of CSV file paths (from radar_graph.py --raw-log)
            label_map: Optional dict mapping label strings to class indices.
                       If None, auto-generated from the data.
            use_differential: If True, append temporal difference features.
        """
        self.samples = []
        self.labels = []
        self.label_map = label_map or {}
        self.use_differential = use_differential

        all_labels = set()

        # ── Load and parse all CSV files ─────────────────────────────
        for filepath in csv_files:
            print(f"[TRAIN] Loading: {filepath}")
            df = pd.read_csv(filepath)

            if 'label' not in df.columns:
                print(f"  WARNING: No 'label' column in {filepath}. Skipping.")
                continue

            # Extract amplitude and phase columns
            amp_cols = [c for c in df.columns if c.startswith("amp_")]
            phase_cols = [c for c in df.columns if c.startswith("phase_")]

            if not amp_cols or not phase_cols:
                print(f"  WARNING: No amp_/phase_ columns in {filepath}. Skipping.")
                continue

            # Get unique labels in this file
            file_labels = df['label'].unique()
            all_labels.update(file_labels)

            print(f"  Loaded {len(df)} packets, labels: {list(file_labels)}")
            print(f"  Subcarriers: {len(amp_cols)} amp + {len(phase_cols)} phase")

            # Extract amplitude and phase matrices
            amp_data = df[amp_cols].values.astype(np.float32)
            phase_data = df[phase_cols].values.astype(np.float32)
            labels = df['label'].values

            # ── Create sliding window samples ────────────────────────
            for start in range(0, len(df) - WINDOW_SIZE, STRIDE):
                end = start + WINDOW_SIZE

                # Only create sample if all packets in window have the same label
                window_labels = labels[start:end]
                if len(set(window_labels)) != 1:
                    continue

                label_str = window_labels[0]

                # Combine amplitude and phase into one feature vector
                window_amp = amp_data[start:end]     # (WINDOW_SIZE, num_subcarriers)
                window_phase = phase_data[start:end]  # (WINDOW_SIZE, num_subcarriers)
                features = np.concatenate([window_amp, window_phase], axis=1).flatten()

                # Append differential features (temporal changes)
                if self.use_differential:
                    amp_diff = np.diff(window_amp, axis=0)    # (WINDOW_SIZE-1, subcarriers)
                    phase_diff = np.diff(window_phase, axis=0)
                    diff_features = np.concatenate([amp_diff, phase_diff], axis=1).flatten()
                    features = np.concatenate([features, diff_features])

                self.samples.append(features)
                self.labels.append(label_str)

        # ── Build label map ──────────────────────────────────────────
        if not self.label_map:
            sorted_labels = sorted(all_labels)
            self.label_map = {label: idx for idx, label in enumerate(sorted_labels)}

        print(f"\n[TRAIN] Label mapping: {self.label_map}")
        if self.use_differential:
            print(f"[TRAIN] Differential features: ENABLED (adds temporal-change robustness)")
        print(f"[TRAIN] Total samples: {len(self.samples)}")

        # Print class distribution
        from collections import Counter
        dist = Counter(self.labels)
        for label, count in sorted(dist.items()):
            print(f"  {label}: {count} samples")

        # Convert labels to integer indices
        self.label_indices = [self.label_map.get(l, 0) for l in self.labels]

        # Convert to numpy
        if self.samples:
            self.samples = np.array(self.samples, dtype=np.float32)
        else:
            self.samples = np.empty((0, WINDOW_SIZE * NORMALIZED_SUBCARRIER_COUNT * 2), dtype=np.float32)

    def augment(self):
        """Apply data augmentation to increase training data diversity."""
        if len(self.samples) == 0:
            return

        original_count = len(self.samples)
        aug_samples = []
        aug_labels = []

        for i in range(len(self.samples)):
            for _ in range(AUGMENT_COPIES):
                sample = self.samples[i].copy()
                feature_len = len(sample)
                sc_count = NORMALIZED_SUBCARRIER_COUNT
                window = WINDOW_SIZE

                # 1. Gaussian noise injection
                noise_std = AUGMENT_NOISE_STD * np.std(sample)
                sample += np.random.normal(0, max(noise_std, 1e-6), feature_len).astype(np.float32)

                # 2. Amplitude scaling (only raw amplitude portion)
                # With differential features, layout is:
                #   [raw_amp | raw_phase | diff_amp | diff_phase]
                # Without differential: [raw_amp | raw_phase]
                scale = np.random.uniform(*AUGMENT_SCALE_RANGE)
                raw_feature_len = window * sc_count * 2  # raw amp + raw phase
                amp_end = window * sc_count  # Raw amplitude ends here
                sample[:amp_end] *= scale

                # 3. Time shift (circular shift within the window)
                shift = np.random.randint(-AUGMENT_TIME_SHIFT_MAX, AUGMENT_TIME_SHIFT_MAX + 1)
                if shift != 0:
                    # Reshape to (window, features_per_packet), roll, flatten
                    per_packet = feature_len // window
                    reshaped = sample.reshape(window, per_packet) if feature_len % window == 0 else None
                    if reshaped is not None:
                        reshaped = np.roll(reshaped, shift, axis=0)
                        sample = reshaped.flatten()

                aug_samples.append(sample)
                aug_labels.append(self.label_indices[i])

        # Append augmented data
        aug_samples = np.array(aug_samples, dtype=np.float32)
        self.samples = np.concatenate([self.samples, aug_samples], axis=0)
        self.label_indices = self.label_indices + aug_labels
        self.labels = self.labels + [self.class_names[l] for l in aug_labels]

        print(f"[TRAIN] Data augmentation: {original_count} -> {len(self.samples)} samples "
              f"({AUGMENT_COPIES}x augmented copies with noise, scaling, and time-shift)")

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        x = torch.FloatTensor(self.samples[idx]).unsqueeze(0)  # (1, features)
        y = self.label_indices[idx]
        return x, y

    @property
    def input_size(self):
        if len(self.samples) > 0:
            return self.samples.shape[1]
        return WINDOW_SIZE * NORMALIZED_SUBCARRIER_COUNT * 2

    @property
    def num_classes(self):
        return len(self.label_map)

    @property
    def class_names(self):
        return [k for k, v in sorted(self.label_map.items(), key=lambda x: x[1])]


# ═══════════════════════════════════════════════════════════════════════════
# TRAINING
# ═══════════════════════════════════════════════════════════════════════════

def train_model(dataset, output_path="shadow_neural_model.pt"):
    """Train the CSINet model and save it."""

    if len(dataset) < 10:
        print("[ERROR] Not enough data to train. Need at least 10 samples.")
        print("[ERROR] Record more data with: python radar_graph.py --port COM8 --record empty --raw-log raw_empty.csv")
        return None

    # ── Train/test split ─────────────────────────────────────────────
    torch.manual_seed(RANDOM_SEED)
    train_size = int(TRAIN_SPLIT * len(dataset))
    test_size = len(dataset) - train_size

    train_dataset, test_dataset = random_split(dataset, [train_size, test_size])

    train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True, drop_last=False)
    test_loader = DataLoader(test_dataset, batch_size=BATCH_SIZE, shuffle=False)

    print(f"\n[TRAIN] Train samples: {train_size}, Test samples: {test_size}")

    # ── Initialize model ───────────────────────────────────────
    model = CSINet(input_size=dataset.input_size, num_classes=dataset.num_classes)

    # ── Compute class weights for imbalanced data ─────────────────
    from collections import Counter
    label_counts = Counter(dataset.label_indices)
    total_samples = sum(label_counts.values())
    num_classes = dataset.num_classes
    class_weights = []
    for cls_idx in range(num_classes):
        count = label_counts.get(cls_idx, 1)
        weight = total_samples / (num_classes * count)
        class_weights.append(weight)
    class_weights_tensor = torch.FloatTensor(class_weights)
    print(f"[TRAIN] Class weights: {dict(zip(dataset.class_names, [f'{w:.2f}' for w in class_weights]))}")

    criterion = nn.CrossEntropyLoss(weight=class_weights_tensor)
    optimizer = optim.Adam(model.parameters(), lr=LEARNING_RATE, weight_decay=1e-4)
    scheduler = optim.lr_scheduler.StepLR(optimizer, step_size=15, gamma=0.5)

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model.to(device)
    print(f"[TRAIN] Device: {device}")
    print(f"[TRAIN] Model parameters: {sum(p.numel() for p in model.parameters()):,}")

    # ── Training loop ────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  TRAINING -- {NUM_EPOCHS} epochs")
    print(f"{'='*60}\n")

    train_losses = []
    train_accs = []
    test_accs = []
    best_test_acc = 0.0
    best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
    best_preds = []
    best_true = []

    for epoch in range(NUM_EPOCHS):
        model.train()
        epoch_loss = 0.0
        correct = 0
        total = 0

        for batch_x, batch_y in train_loader:
            batch_x = batch_x.to(device)
            batch_y = torch.LongTensor(batch_y).to(device)

            optimizer.zero_grad()
            outputs = model(batch_x)
            loss = criterion(outputs, batch_y)
            loss.backward()
            optimizer.step()

            epoch_loss += loss.item()
            _, predicted = torch.max(outputs, 1)
            total += batch_y.size(0)
            correct += (predicted == batch_y).sum().item()

        scheduler.step()

        train_acc = correct / total if total > 0 else 0
        avg_loss = epoch_loss / len(train_loader) if len(train_loader) > 0 else 0
        train_losses.append(avg_loss)
        train_accs.append(train_acc)

        # ── Evaluate on test set ─────────────────────────────────────
        model.eval()
        test_correct = 0
        test_total = 0
        all_preds = []
        all_true = []

        with torch.no_grad():
            for batch_x, batch_y in test_loader:
                batch_x = batch_x.to(device)
                batch_y = torch.LongTensor(batch_y).to(device)

                outputs = model(batch_x)
                _, predicted = torch.max(outputs, 1)
                test_total += batch_y.size(0)
                test_correct += (predicted == batch_y).sum().item()
                all_preds.extend(predicted.cpu().numpy())
                all_true.extend(batch_y.cpu().numpy())

        test_acc = test_correct / test_total if test_total > 0 else 0
        test_accs.append(test_acc)

        # Print progress every epoch
        print(f"  Epoch {epoch+1:3d}/{NUM_EPOCHS}  |  "
                  f"Loss: {avg_loss:.4f}  |  "
                  f"Train Acc: {train_acc:.1%}  |  "
                  f"Test Acc: {test_acc:.1%}")

        # Save best model
        if test_acc > best_test_acc:
            best_test_acc = test_acc
            best_preds = all_preds
            best_true = all_true
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}

    # ── Final evaluation ─────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  TRAINING COMPLETE")
    print(f"{'='*60}")
    print(f"\n  Best test accuracy: {best_test_acc:.1%}")

    # Classification report
    print(f"\n  Classification Report:")
    print(classification_report(best_true, best_preds,
                                 target_names=dataset.class_names, digits=3))

    # Confusion matrix
    cm = confusion_matrix(best_true, best_preds)
    print(f"  Confusion Matrix:")
    print(f"  {cm}")

    # ── Save model ───────────────────────────────────────────────────
    checkpoint = {
        'model_state_dict': best_state,
        'input_size': dataset.input_size,
        'num_classes': dataset.num_classes,
        'class_names': dataset.class_names,
        'label_map': dataset.label_map,
        'window_size': WINDOW_SIZE,
        'normalized_subcarrier_count': NORMALIZED_SUBCARRIER_COUNT,
        'use_differential': dataset.use_differential,
        'test_accuracy': f"{best_test_acc:.1%}",
        'confusion_matrix': cm.tolist(),
        'train_losses': train_losses,
        'train_accs': train_accs,
        'test_accs': test_accs,
    }

    torch.save(checkpoint, output_path)
    print(f"\n  Model saved to: {output_path}")
    print(f"  Use with: python radar_graph.py --port COM8 --ai")

    # ── Save training results JSON ───────────────────────────────────
    results = {
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        'num_samples': len(dataset),
        'num_classes': dataset.num_classes,
        'class_names': dataset.class_names,
        'test_accuracy': best_test_acc,
        'confusion_matrix': cm.tolist(),
        'classification_report': classification_report(
            best_true, best_preds,
            target_names=dataset.class_names, digits=3, output_dict=True),
    }

    results_path = output_path.replace('.pt', '_results.json')
    with open(results_path, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"  Results saved to: {results_path}")

    # ── Plot training curves ─────────────────────────────────────────
    if plt is not None:
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
        fig.suptitle("PROJECT SHADOW -- Neural Network Training", fontsize=14, fontweight='bold')

        ax1.plot(train_losses, color='#f85149', linewidth=2)
        ax1.set_title("Training Loss")
        ax1.set_xlabel("Epoch")
        ax1.set_ylabel("Cross-Entropy Loss")
        ax1.grid(True, alpha=0.3)

        ax2.plot(train_accs, label='Train', color='#58a6ff', linewidth=2)
        ax2.plot(test_accs, label='Test', color='#3fb950', linewidth=2)
        ax2.set_title("Accuracy")
        ax2.set_xlabel("Epoch")
        ax2.set_ylabel("Accuracy")
        ax2.legend()
        ax2.grid(True, alpha=0.3)

        plt.tight_layout()
        plot_path = output_path.replace('.pt', '_training_curves.png')
        plt.savefig(plot_path, dpi=150)
        print(f"  Training curves saved to: {plot_path}")
        plt.close()

    return best_test_acc


# ═══════════════════════════════════════════════════════════════════════════
# FINE-TUNING (Rapid adaptation to new environment)
# ═══════════════════════════════════════════════════════════════════════════

def finetune_model(base_model_path: str, dataset, output_path: str,
                   finetune_epochs: int = 10, finetune_lr: float = 0.0001):
    """
    Fine-tune an existing model on new data from a different environment.

    Strategy:
      1. Load the pre-trained model weights
      2. Freeze the feature extractor (convolutional layers)
      3. Retrain only the classifier (fully connected layers) with low LR
      4. Save the adapted model

    This enables rapid adaptation with just 1-2 minutes of new data.
    """
    print(f"\n{'='*60}")
    print(f"  FINE-TUNING -- Adapting to new environment")
    print(f"{'='*60}")

    # Load base model
    if not os.path.exists(base_model_path):
        print(f"[ERROR] Base model not found: {base_model_path}")
        return None

    checkpoint = torch.load(base_model_path, map_location='cpu', weights_only=False)
    base_input_size = checkpoint.get('input_size')
    num_classes = checkpoint.get('num_classes', 2)
    class_names = checkpoint.get('class_names', ['empty', 'walking'])

    print(f"  Base model: {base_model_path}")
    print(f"  Base accuracy: {checkpoint.get('test_accuracy', 'N/A')}")
    print(f"  Classes: {class_names}")

    # Check input size compatibility
    if base_input_size != dataset.input_size:
        print(f"  WARNING: Input size mismatch!")
        print(f"    Base model: {base_input_size}")
        print(f"    New data:   {dataset.input_size}")
        print(f"  Retraining from scratch instead of fine-tuning.")
        return train_model(dataset, output_path=output_path)

    # Load model and freeze feature extractor
    model = CSINet(input_size=base_input_size, num_classes=num_classes)
    model.load_state_dict(checkpoint['model_state_dict'])

    # Freeze convolutional feature layers
    frozen_count = 0
    for name, param in model.features.named_parameters():
        param.requires_grad = False
        frozen_count += 1

    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    print(f"  Frozen: {frozen_count} layer groups (feature extractor)")
    print(f"  Trainable: {trainable:,} / {total:,} parameters (classifier only)")
    print(f"  Fine-tune LR: {finetune_lr}, Epochs: {finetune_epochs}")

    # Split data
    torch.manual_seed(RANDOM_SEED)
    train_size = int(TRAIN_SPLIT * len(dataset))
    test_size = len(dataset) - train_size
    train_dataset, test_dataset = random_split(dataset, [train_size, test_size])

    train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True)
    test_loader = DataLoader(test_dataset, batch_size=BATCH_SIZE, shuffle=False)

    # Only optimize classifier parameters
    optimizer = optim.Adam(
        filter(lambda p: p.requires_grad, model.parameters()),
        lr=finetune_lr, weight_decay=1e-4
    )
    criterion = nn.CrossEntropyLoss()

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model.to(device)

    # Training loop
    print(f"\n  Fine-tuning...")
    best_acc = 0.0
    best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}

    for epoch in range(finetune_epochs):
        model.train()
        for batch_x, batch_y in train_loader:
            batch_x = batch_x.to(device)
            batch_y = torch.LongTensor(batch_y).to(device)
            optimizer.zero_grad()
            outputs = model(batch_x)
            loss = criterion(outputs, batch_y)
            loss.backward()
            optimizer.step()

        # Evaluate
        model.eval()
        correct = total_test = 0
        with torch.no_grad():
            for batch_x, batch_y in test_loader:
                batch_x = batch_x.to(device)
                batch_y = torch.LongTensor(batch_y).to(device)
                outputs = model(batch_x)
                _, predicted = torch.max(outputs, 1)
                total_test += batch_y.size(0)
                correct += (predicted == batch_y).sum().item()

        acc = correct / total_test if total_test > 0 else 0
        if acc > best_acc:
            best_acc = acc
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}

        if (epoch + 1) % 2 == 0 or epoch == 0:
            print(f"    Epoch {epoch+1}/{finetune_epochs}  |  Test Acc: {acc:.1%}")

    # Save fine-tuned model
    ft_checkpoint = dict(checkpoint)  # Inherit metadata from base model
    ft_checkpoint['model_state_dict'] = best_state
    ft_checkpoint['test_accuracy'] = f"{best_acc:.1%}"
    ft_checkpoint['fine_tuned_from'] = base_model_path
    ft_checkpoint['use_differential'] = dataset.use_differential

    torch.save(ft_checkpoint, output_path)
    print(f"\n  Fine-tuned model saved to: {output_path}")
    print(f"  Adapted accuracy: {best_acc:.1%}")
    print(f"  Use with: python radar_graph.py --port COM8 --ai")

    return best_acc


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    global NUM_EPOCHS, BATCH_SIZE, LEARNING_RATE
    parser = argparse.ArgumentParser(
        description="PROJECT SHADOW -- Train Neural Network for CSI Motion Classification",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Train with 2 classes (empty vs walking):
  python train_model.py --data raw_empty.csv raw_walking.csv

  # Train with 3 classes (empty vs walking vs weapon):
  python train_model.py --data raw_empty.csv raw_walking.csv raw_weapon.csv

  # Train with differential features (more robust to setup changes):
  python train_model.py --data raw_empty.csv raw_walking.csv --differential

  # Fine-tune existing model on new environment data (fast adaptation):
  python train_model.py --data new_empty.csv new_walking.csv --finetune shadow_neural_model.pt

  # Custom output path and epochs:
  python train_model.py --data raw_empty.csv raw_walking.csv --output my_model.pt --epochs 100
        """,
    )
    parser.add_argument("--data", nargs="+", required=True,
                        help="CSV files from radar_graph.py --raw-log (one per class)")
    parser.add_argument("--output", default="shadow_neural_model.pt",
                        help="Output model path (default: shadow_neural_model.pt)")
    parser.add_argument("--epochs", type=int, default=NUM_EPOCHS,
                        help=f"Number of training epochs (default: {NUM_EPOCHS})")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE,
                        help=f"Batch size (default: {BATCH_SIZE})")
    parser.add_argument("--lr", type=float, default=LEARNING_RATE,
                        help=f"Learning rate (default: {LEARNING_RATE})")
    parser.add_argument("--augment", action="store_true", default=True,
                        help="Enable data augmentation (default: enabled)")
    parser.add_argument("--no-augment", action="store_false", dest="augment",
                        help="Disable data augmentation")
    parser.add_argument("--differential", action="store_true", default=False,
                        help="Use differential features (temporal changes) for robustness")
    parser.add_argument("--finetune", type=str, default=None, metavar="MODEL.pt",
                        help="Fine-tune an existing model instead of training from scratch")
    parser.add_argument("--finetune-epochs", type=int, default=10,
                        help="Epochs for fine-tuning (default: 10)")
    parser.add_argument("--finetune-lr", type=float, default=0.0001,
                        help="Learning rate for fine-tuning (default: 0.0001)")

    args = parser.parse_args()

    # Override globals
    NUM_EPOCHS = args.epochs
    BATCH_SIZE = args.batch_size
    LEARNING_RATE = args.lr

    print("=" * 60)
    print("  PROJECT SHADOW -- Neural Network Trainer")
    print("=" * 60)
    print()

    # Verify files exist
    for f in args.data:
        if not os.path.exists(f):
            print(f"[ERROR] File not found: {f}")
            sys.exit(1)

    # If fine-tuning, inherit differential setting from base model
    use_differential = args.differential
    if args.finetune and os.path.exists(args.finetune):
        base_ckpt = torch.load(args.finetune, map_location='cpu', weights_only=False)
        base_diff = base_ckpt.get('use_differential', False)
        if base_diff and not args.differential:
            print(f"[TRAIN] Base model used differential features -- enabling automatically.")
            use_differential = True

    # Load dataset
    dataset = CSIDataset(args.data, use_differential=use_differential)

    if dataset.num_classes < 2:
        print("[ERROR] Need at least 2 classes to train. Record more data with different labels.")
        sys.exit(1)

    # Apply data augmentation
    if args.augment:
        dataset.augment()
    else:
        print("[TRAIN] Data augmentation disabled.")

    # Fine-tune or train from scratch
    if args.finetune:
        acc = finetune_model(
            base_model_path=args.finetune,
            dataset=dataset,
            output_path=args.output,
            finetune_epochs=args.finetune_epochs,
            finetune_lr=args.finetune_lr,
        )
    else:
        acc = train_model(dataset, output_path=args.output)

    if acc is not None:
        print(f"\n{'='*60}")
        print(f"  DONE! Model ready for deployment.")
        print(f"  Test with: python radar_graph.py --port COM8 --ai")
        print(f"{'='*60}")


if __name__ == "__main__":
    main()
