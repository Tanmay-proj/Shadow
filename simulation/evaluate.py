#!/usr/bin/env python3
"""
PROJECT SHADOW — Quantitative Evaluation Script
=================================================

Evaluates the performance of the Wi-Fi CSI motion detection system
by computing accuracy, precision, recall, F1-score, and generating
ROC curves and confusion matrices.

Works with both:
  - Processed motion index CSVs (from --record)
  - Raw CSI log CSVs (from --raw-log)
  - Trained neural model output

Usage:
    python evaluate.py --motion-csvs csi_features_empty_*.csv csi_features_walking_*.csv
    python evaluate.py --raw-csvs raw_empty.csv raw_walking.csv
    python evaluate.py --model shadow_neural_model.pt --raw-csvs raw_empty.csv raw_walking.csv

Author: PROJECT SHADOW
"""

import argparse
import glob
import json
import os
import sys
import numpy as np
import pandas as pd
from pathlib import Path

try:
    from sklearn.metrics import (
        classification_report, confusion_matrix, roc_curve, auc,
        accuracy_score, precision_recall_fscore_support, f1_score
    )
except ImportError:
    print("ERROR: scikit-learn required. Install: pip install scikit-learn")
    sys.exit(1)

try:
    import matplotlib
    matplotlib.use("TkAgg")
    import matplotlib.pyplot as plt
    import matplotlib.gridspec as gridspec
except ImportError:
    print("ERROR: matplotlib required. Install: pip install matplotlib")
    sys.exit(1)

try:
    import torch
except ImportError:
    torch = None


# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

NORMALIZED_SUBCARRIER_COUNT = 52
NEURAL_WINDOW = 20
STRIDE = 5
CONSECUTIVE_HITS = 3  # Must match MOTION_CONSECUTIVE_HITS in radar_graph.py


# ═══════════════════════════════════════════════════════════════════════════
# MOTION INDEX CSV EVALUATION (Classical DSP)
# ═══════════════════════════════════════════════════════════════════════════

def evaluate_motion_csvs(csv_files: list, labels: list):
    """
    Evaluate the classical DSP motion index threshold approach.

    Each CSV has columns: timestamp, motion_index
    Labels are provided per-file (e.g., 'empty' or 'walking').

    Sweeps across threshold values and finds the optimal one.
    """
    print("\n" + "=" * 60)
    print("  CLASSICAL DSP -- Motion Index Threshold Evaluation")
    print("=" * 60)

    all_values = []
    all_labels = []

    file_boundaries = []  # Track where each file's data starts

    for csv_path, label in zip(csv_files, labels):
        df = pd.read_csv(csv_path)
        if 'motion_index' not in df.columns:
            print(f"  WARNING: {csv_path} has no 'motion_index' column. Skipping.")
            continue

        values = df['motion_index'].values
        print(f"  Loaded {csv_path}: {len(values)} samples, label='{label}'")
        print(f"    Mean: {np.mean(values):.2f}, Std: {np.std(values):.2f}, "
              f"Min: {np.min(values):.2f}, Max: {np.max(values):.2f}")

        file_boundaries.append(len(all_values))  # Mark start index of this file
        all_values.extend(values)
        all_labels.extend([1 if label != 'empty' else 0] * len(values))

    all_values = np.array(all_values)
    all_labels = np.array(all_labels)

    if len(all_values) == 0:
        print("  ERROR: No valid data loaded.")
        return None

    # ── Sweep thresholds (with consecutive-hit logic matching live system) ──
    thresholds = np.linspace(np.min(all_values), np.max(all_values), 200)
    best_f1 = 0
    best_threshold = 0
    best_results = {}

    f1_scores_sweep = []

    def apply_consecutive_hits(values, threshold, n_hits, boundaries=None):
        """Mimic the live system's consecutive-hit detection logic.
        Resets the consecutive counter at file boundaries to avoid
        cross-file contamination."""
        boundary_set = set(boundaries) if boundaries else set()
        predictions = np.zeros(len(values), dtype=int)
        consecutive = 0
        for i, v in enumerate(values):
            if i in boundary_set:
                consecutive = 0  # Reset at file boundary
            if v > threshold:
                consecutive += 1
            else:
                consecutive = 0
            predictions[i] = 1 if consecutive >= n_hits else 0
        return predictions

    for thresh in thresholds:
        predictions = apply_consecutive_hits(all_values, thresh, CONSECUTIVE_HITS, file_boundaries)
        f1 = f1_score(all_labels, predictions, zero_division=0)
        f1_scores_sweep.append(f1)

        if f1 > best_f1:
            best_f1 = f1
            best_threshold = thresh
            acc = accuracy_score(all_labels, predictions)
            prec, rec, _, _ = precision_recall_fscore_support(
                all_labels, predictions, average='binary', zero_division=0)
            best_results = {
                'threshold': float(best_threshold),
                'accuracy': float(acc),
                'precision': float(prec),
                'recall': float(rec),
                'f1_score': float(best_f1),
            }

    print(f"\n  Optimal Threshold: {best_threshold:.2f}")
    print(f"  Accuracy:  {best_results['accuracy']:.1%}")
    print(f"  Precision: {best_results['precision']:.1%}")
    print(f"  Recall:    {best_results['recall']:.1%}")
    print(f"  F1-Score:  {best_results['f1_score']:.1%}")

    # ── Confusion Matrix ─────────────────────────────────────────────
    best_preds = apply_consecutive_hits(all_values, best_threshold, CONSECUTIVE_HITS, file_boundaries)
    cm = confusion_matrix(all_labels, best_preds)
    print(f"\n  Confusion Matrix:")
    print(f"              Predicted")
    print(f"              Empty  Motion")
    print(f"  Actual Empty   {cm[0][0]:5d}  {cm[0][1]:5d}")
    print(f"  Actual Motion  {cm[1][0]:5d}  {cm[1][1]:5d}")

    # ── ROC Curve ────────────────────────────────────────────────────
    fpr, tpr, _ = roc_curve(all_labels, all_values)
    roc_auc = auc(fpr, tpr)
    print(f"\n  ROC AUC: {roc_auc:.3f}")

    best_results['roc_auc'] = float(roc_auc)
    best_results['confusion_matrix'] = cm.tolist()

    return {
        'all_values': all_values,
        'all_labels': all_labels,
        'best_threshold': best_threshold,
        'results': best_results,
        'fpr': fpr,
        'tpr': tpr,
        'roc_auc': roc_auc,
        'thresholds_sweep': thresholds,
        'f1_scores_sweep': np.array(f1_scores_sweep),
        'confusion_matrix': cm,
    }


# ═══════════════════════════════════════════════════════════════════════════
# NEURAL MODEL EVALUATION
# ═══════════════════════════════════════════════════════════════════════════

def evaluate_neural_model(model_path: str, csv_files: list):
    """Evaluate the trained neural model on raw CSI data."""

    if torch is None:
        print("  ERROR: PyTorch not installed. Cannot evaluate neural model.")
        return None

    print("\n" + "=" * 60)
    print("  NEURAL NETWORK -- CSINet Evaluation")
    print("=" * 60)

    # Load model
    checkpoint = torch.load(model_path, map_location='cpu', weights_only=False)
    class_names = checkpoint.get('class_names', ['empty', 'walking'])
    label_map = checkpoint.get('label_map', {name: i for i, name in enumerate(class_names)})

    print(f"  Model: {model_path}")
    print(f"  Classes: {class_names}")
    print(f"  Training accuracy: {checkpoint.get('test_accuracy', 'N/A')}")

    # Import CSINet and dataset from train_model
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from train_model import CSINet, CSIDataset

    # Check if model was trained with differential features
    use_differential = checkpoint.get('use_differential', False)
    if use_differential:
        print(f"  Model uses differential features -- enabling in dataset.")

    # Load dataset with matching feature configuration
    dataset = CSIDataset(csv_files, label_map=label_map, use_differential=use_differential)

    if len(dataset) == 0:
        print("  ERROR: No valid samples loaded.")
        return None

    # Load model weights
    model = CSINet(input_size=dataset.input_size, num_classes=dataset.num_classes)
    model.load_state_dict(checkpoint['model_state_dict'])
    model.eval()

    # Run inference on all samples
    from torch.utils.data import DataLoader
    loader = DataLoader(dataset, batch_size=64, shuffle=False)

    all_preds = []
    all_probs = []
    all_true = []

    with torch.no_grad():
        for batch_x, batch_y in loader:
            outputs = model(batch_x)
            probs = torch.softmax(outputs, dim=1)
            _, predicted = torch.max(outputs, 1)

            all_preds.extend(predicted.numpy())
            all_probs.extend(probs.numpy())
            all_true.extend(batch_y if isinstance(batch_y, list) else batch_y.numpy())

    all_preds = np.array(all_preds)
    all_true = np.array(all_true)
    all_probs = np.array(all_probs)

    # Metrics
    acc = accuracy_score(all_true, all_preds)
    print(f"\n  Overall Accuracy: {acc:.1%}")
    print(f"\n  Classification Report:")
    print(classification_report(all_true, all_preds,
                                 target_names=class_names, digits=3))

    cm = confusion_matrix(all_true, all_preds)
    print(f"  Confusion Matrix:")
    print(f"  {cm}")

    # ROC (for binary classification)
    roc_data = None
    if len(class_names) == 2 and all_probs.shape[1] == 2:
        fpr, tpr, _ = roc_curve(all_true, all_probs[:, 1])
        roc_auc = auc(fpr, tpr)
        print(f"\n  ROC AUC: {roc_auc:.3f}")
        roc_data = {'fpr': fpr, 'tpr': tpr, 'roc_auc': roc_auc}

    return {
        'accuracy': acc,
        'confusion_matrix': cm,
        'class_names': class_names,
        'all_preds': all_preds,
        'all_true': all_true,
        'all_probs': all_probs,
        'roc_data': roc_data,
    }


# ═══════════════════════════════════════════════════════════════════════════
# VISUALIZATION
# ═══════════════════════════════════════════════════════════════════════════

def plot_results(classical_results=None, neural_results=None, output_dir="."):
    """Generate comprehensive evaluation plots."""

    has_classical = classical_results is not None
    has_neural = neural_results is not None

    num_cols = (1 if has_classical else 0) + (1 if has_neural else 0)
    if num_cols == 0:
        return

    fig = plt.figure(figsize=(7 * num_cols, 12))
    fig.suptitle("PROJECT SHADOW -- Evaluation Results",
                 fontsize=16, fontweight='bold', y=0.98)

    col_idx = 0

    # ── Classical DSP plots ──────────────────────────────────────────
    if has_classical:
        col_idx += 1
        gs = gridspec.GridSpec(3, num_cols, figure=fig)

        # Distribution plot
        ax1 = fig.add_subplot(gs[0, col_idx - 1])
        empty_vals = classical_results['all_values'][classical_results['all_labels'] == 0]
        motion_vals = classical_results['all_values'][classical_results['all_labels'] == 1]

        ax1.hist(empty_vals, bins=50, alpha=0.7, label='Empty', color='#3fb950', density=True)
        ax1.hist(motion_vals, bins=50, alpha=0.7, label='Motion', color='#f85149', density=True)
        ax1.axvline(classical_results['best_threshold'], color='white', linestyle='--',
                    linewidth=2, label=f"Threshold: {classical_results['best_threshold']:.1f}")
        ax1.set_title("Classical DSP -- Motion Index Distribution", fontweight='bold')
        ax1.set_xlabel("Motion Index")
        ax1.set_ylabel("Density")
        ax1.legend()
        ax1.grid(True, alpha=0.2)

        # F1 vs Threshold
        ax2 = fig.add_subplot(gs[1, col_idx - 1])
        ax2.plot(classical_results['thresholds_sweep'],
                 classical_results['f1_scores_sweep'],
                 color='#58a6ff', linewidth=2)
        ax2.axvline(classical_results['best_threshold'], color='#f85149',
                    linestyle='--', label=f"Best: {classical_results['best_threshold']:.1f}")
        ax2.set_title("F1-Score vs Threshold", fontweight='bold')
        ax2.set_xlabel("Threshold")
        ax2.set_ylabel("F1-Score")
        ax2.legend()
        ax2.grid(True, alpha=0.2)

        # ROC Curve
        ax3 = fig.add_subplot(gs[2, col_idx - 1])
        ax3.plot(classical_results['fpr'], classical_results['tpr'],
                 color='#58a6ff', linewidth=2,
                 label=f"Classical DSP (AUC={classical_results['roc_auc']:.3f})")
        ax3.plot([0, 1], [0, 1], 'w--', alpha=0.3)
        ax3.set_title("ROC Curve", fontweight='bold')
        ax3.set_xlabel("False Positive Rate")
        ax3.set_ylabel("True Positive Rate")
        ax3.legend()
        ax3.grid(True, alpha=0.2)

    # ── Neural Network plots ─────────────────────────────────────────
    if has_neural:
        col_idx += 1
        gs = gridspec.GridSpec(3, num_cols, figure=fig)

        # Confusion matrix heatmap
        ax4 = fig.add_subplot(gs[0, col_idx - 1])
        cm = neural_results['confusion_matrix']
        im = ax4.imshow(cm, interpolation='nearest', cmap='Blues')
        ax4.set_title(f"Neural Network -- Confusion Matrix\n"
                      f"Accuracy: {neural_results['accuracy']:.1%}",
                      fontweight='bold')

        class_names = neural_results['class_names']
        tick_marks = np.arange(len(class_names))
        ax4.set_xticks(tick_marks)
        ax4.set_xticklabels(class_names)
        ax4.set_yticks(tick_marks)
        ax4.set_yticklabels(class_names)
        ax4.set_xlabel("Predicted")
        ax4.set_ylabel("Actual")

        # Add text annotations
        for i in range(cm.shape[0]):
            for j in range(cm.shape[1]):
                ax4.text(j, i, str(cm[i, j]),
                        ha='center', va='center',
                        color='white' if cm[i, j] > cm.max() / 2 else 'black',
                        fontsize=14, fontweight='bold')

        # ROC for neural (if binary)
        if neural_results.get('roc_data'):
            ax5 = fig.add_subplot(gs[1, col_idx - 1])
            rd = neural_results['roc_data']
            ax5.plot(rd['fpr'], rd['tpr'],
                     color='#3fb950', linewidth=2,
                     label=f"Neural (AUC={rd['roc_auc']:.3f})")

            # Overlay classical ROC if available
            if has_classical:
                ax5.plot(classical_results['fpr'], classical_results['tpr'],
                         color='#58a6ff', linewidth=2, alpha=0.6,
                         label=f"Classical (AUC={classical_results['roc_auc']:.3f})")

            ax5.plot([0, 1], [0, 1], 'w--', alpha=0.3)
            ax5.set_title("ROC Comparison", fontweight='bold')
            ax5.set_xlabel("False Positive Rate")
            ax5.set_ylabel("True Positive Rate")
            ax5.legend()
            ax5.grid(True, alpha=0.2)

        # Per-class accuracy bars
        ax6 = fig.add_subplot(gs[2, col_idx - 1])
        per_class_acc = cm.diagonal() / cm.sum(axis=1)
        colors = ['#3fb950', '#f85149', '#58a6ff', '#e3b341'][:len(class_names)]
        bars = ax6.bar(class_names, per_class_acc, color=colors, alpha=0.8)
        ax6.set_title("Per-Class Accuracy", fontweight='bold')
        ax6.set_ylabel("Accuracy")
        ax6.set_ylim(0, 1.1)

        for bar, acc_val in zip(bars, per_class_acc):
            ax6.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.02,
                    f'{acc_val:.1%}', ha='center', fontweight='bold')

        ax6.grid(True, alpha=0.2, axis='y')

    plt.style.use("dark_background")
    plt.tight_layout(rect=[0, 0, 1, 0.95])

    plot_path = os.path.join(output_dir, "evaluation_results.png")
    plt.savefig(plot_path, dpi=150, facecolor='#0a0a0a')
    print(f"\n  Evaluation plots saved to: {plot_path}")
    plt.close()


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="PROJECT SHADOW -- Quantitative Evaluation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Evaluate classical DSP with motion index CSVs:
  python evaluate.py --motion-csvs csi_features_empty_*.csv csi_features_walking_*.csv \\
                     --motion-labels empty walking

  # Evaluate neural model on raw CSI data:
  python evaluate.py --model shadow_neural_model.pt --raw-csvs raw_empty.csv raw_walking.csv

  # Evaluate both and compare:
  python evaluate.py --motion-csvs csi_features_empty_*.csv csi_features_walking_*.csv \\
                     --motion-labels empty walking \\
                     --model shadow_neural_model.pt --raw-csvs raw_empty.csv raw_walking.csv
        """,
    )
    parser.add_argument("--motion-csvs", nargs="+",
                        help="Motion index CSV files (from --record)")
    parser.add_argument("--motion-labels", nargs="+",
                        help="Labels for motion CSVs (e.g., 'empty' 'walking')")
    parser.add_argument("--model", type=str,
                        help="Path to trained neural model (.pt)")
    parser.add_argument("--raw-csvs", nargs="+",
                        help="Raw CSI CSV files (from --raw-log)")
    parser.add_argument("--output-dir", default=".",
                        help="Directory for output files")

    args = parser.parse_args()

    print("=" * 60)
    print("  PROJECT SHADOW -- Quantitative Evaluation")
    print("=" * 60)

    classical_results = None
    neural_results = None

    # ── Classical DSP evaluation ─────────────────────────────────────
    if args.motion_csvs and args.motion_labels:
        if len(args.motion_csvs) != len(args.motion_labels):
            print("[ERROR] Number of CSVs must match number of labels.")
            sys.exit(1)

        classical_results = evaluate_motion_csvs(args.motion_csvs, args.motion_labels)

    # ── Neural model evaluation ──────────────────────────────────────
    if args.model and args.raw_csvs:
        if not os.path.exists(args.model):
            print(f"[ERROR] Model not found: {args.model}")
            sys.exit(1)

        neural_results = evaluate_neural_model(args.model, args.raw_csvs)

    # ── Generate plots ───────────────────────────────────────────────
    if classical_results or neural_results:
        plot_results(classical_results, neural_results, args.output_dir)

        # Save summary JSON
        summary = {
            'timestamp': pd.Timestamp.now().isoformat(),
        }
        if classical_results:
            summary['classical_dsp'] = classical_results['results']
        if neural_results:
            summary['neural_network'] = {
                'accuracy': float(neural_results['accuracy']),
                'class_names': neural_results['class_names'],
                'confusion_matrix': neural_results['confusion_matrix'].tolist(),
            }
            if neural_results.get('roc_data'):
                summary['neural_network']['roc_auc'] = float(neural_results['roc_data']['roc_auc'])

        summary_path = os.path.join(args.output_dir, "evaluation_summary.json")
        with open(summary_path, 'w') as f:
            json.dump(summary, f, indent=2)
        print(f"  Summary saved to: {summary_path}")
    else:
        print("\n[ERROR] No evaluation performed. Provide either:")
        print("  --motion-csvs + --motion-labels  (for classical DSP evaluation)")
        print("  --model + --raw-csvs              (for neural model evaluation)")
        parser.print_help()


if __name__ == "__main__":
    main()
