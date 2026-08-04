# LTE-Pretrained Foundation Model to 5G Transfer Plan

## 1. Goal

Adapt the pretrained 4G/LTE foundation model to the 5G dataset without retraining the full model from scratch.

The main principle is:

- reuse the pretrained 4G backbone as much as possible;
- introduce a new 5G configuration tokenizer because the 5G configuration schema differs from 4G;
- support both categorical and numerical 5G configuration features;
- add lightweight adapters only when the actual 4G/5G tensor interfaces require them;
- preserve the original KPI reconstruction task and the rest of the 4G training pipeline as closely as possible.

Do **not** assume fixed tensor dimensions from this document. Any implementation-dependent dimensions must be detected from the original 4G code/checkpoint and the current 5G dataset.

---

## 2. Required Inputs / Paths

Fill these before implementation:

```text
4G training/model code:
[4G_TRAINING_CODE]

4G pretrained checkpoint:
[4G_PRETRAINED_CHECKPOINT]

Current 5G workspace / training code:
[5G_WORKSPACE]

Categorical-column list:
[CATEGORICAL_COLUMNS_LIST_PATH]

Numerical-column list:
[NUMERICAL_COLUMNS_LIST_PATH]

CSV containing valid categorical values / category mappings for each categorical column:
[CATEGORICAL_VALUES_CSV_PATH]
```

The current 5G dataset loading step is already implemented and verified. Preserve it unless a small change is strictly required to format model inputs.

---

## 3. Mandatory Implementation-Time Interface Discovery

Before implementing the transfer model, inspect the actual code and data.

### 3.1 Reconstruct and load the original 4G model

1. Instantiate the exact architecture used for 4G pretraining.
2. Load:
   ```text
   [4G_PRETRAINED_CHECKPOINT]
   ```
3. Inspect and report:
   - checkpoint keys;
   - model `state_dict` keys;
   - matched keys;
   - missing keys;
   - unexpected keys.
4. Verify that the original 4G model can be reconstructed correctly before adding any 5G-specific modules.

Do not create a new "similar" model from scratch. The transfer model must start from the actual pretrained 4G model/components.

### 3.2 Inspect the original 4G interfaces

Automatically determine from the original implementation:

```text
Original 4G configuration tokenizer output:
[AUTO-DETECT]

Pretrained configuration encoder input:
[AUTO-DETECT]

Pretrained configuration encoder output:
[AUTO-DETECT]

KPI embedding/encoder input:
[AUTO-DETECT]

KPI embedding/encoder output:
[AUTO-DETECT]

Cross-attention query shape:
[AUTO-DETECT]

Cross-attention key/value shape:
[AUTO-DETECT]

Reconstruction-head input/output:
[AUTO-DETECT]

Any fixed token-count assumptions:
[AUTO-DETECT]

Pooling / flattening behavior:
[AUTO-DETECT]

Positional embedding behavior:
[AUTO-DETECT]
```

Explicitly check for assumptions such as:

- fixed 20-token flattening;
- fixed-length positional embeddings;
- linear layers whose input size depends on the original number of 4G configuration features;
- fixed token counts before cross-attention or reconstruction.

### 3.3 Inspect one 5G batch

From the existing 5G dataset implementation, automatically determine:

```text
Number of categorical configuration features:
[AUTO-DETECT]

Number of numerical configuration features:
[AUTO-DETECT]

Total number of 5G configuration features/tokens:
[AUTO-DETECT]

5G KPI names and order:
[AUTO-DETECT]

5G KPI tensor shape:
[AUTO-DETECT]

Missing/unavailable KPI(s):
[AUTO-DETECT]
```

Do not hard-code these values if they can be obtained from the dataset metadata or input files.

---

## 4. 5G Configuration Preprocessing

The 5G configuration data contains both categorical and numerical features.

### 4.1 Categorical features

The current categorical values are still raw values.

Use:

```text
Categorical columns:
[CATEGORICAL_COLUMNS_LIST_PATH]

Categorical mapping information:
[CATEGORICAL_VALUES_CSV_PATH]
```

For each categorical column:

```text
raw categorical value
→ integer category index
→ feature-specific embedding lookup
→ d_model-dimensional token
```

Requirements:

- each categorical column must have its own category vocabulary/mapping;
- use a deterministic mapping;
- handle unknown/unseen values explicitly rather than silently assigning arbitrary indices;
- avoid rebuilding inconsistent mappings independently in train/validation/test.

### 4.2 Numerical features

Use:

```text
Numerical columns:
[NUMERICAL_COLUMNS_LIST_PATH]
```

Follow the FT-Transformer-style feature tokenizer:

```text
scalar numerical value x_j
→ x_j * W_j
→ + optional/learned feature bias b_j
→ d_model-dimensional token
```

where each numerical feature has its own learnable vector `W_j`.

Do not discretize numerical features into categorical indices.

### 4.3 Numerical preprocessing

First inspect the current 5G data preprocessing.

Do not silently introduce a new normalization scheme.

If numerical normalization is needed:

- make it explicit/configurable;
- compute statistics using the training split only;
- apply the same stored statistics to validation/test;
- avoid leakage from validation/test data.

### 4.4 Combined tokenizer output

After tokenization:

```text
categorical tokens
+
numerical tokens
→ stack along the feature/token dimension
→ [B, N_5G_features, d_model]
```

`N_5G_features` must be detected from the current dataset rather than hard-coded.

---

## 5. New 5G Configuration Tokenizer

Introduce a new 5G-specific tokenizer because the 5G configuration schema differs from the original 4G schema.

Conceptually:

```text
5G raw configuration
        ↓
categorical index conversion + numerical preprocessing
        ↓
categorical feature embeddings + numerical feature embeddings
        ↓
5G configuration tokens
        ↓
[B, N_5G_features, d_model]
```

The new tokenizer is randomly/newly initialized and trained on 5G data.

Its purpose is to express the new 5G configuration schema through the latent interface used by the pretrained 4G model.

Do not impose one-to-one correspondence between individual 4G and 5G configuration parameters.

---

## 6. Configuration Encoder Transfer

Reuse the original Transformer-based 4G configuration encoder.

### Main protocol

- load its weights from the 4G pretrained checkpoint;
- keep the original hidden size, attention heads, feed-forward dimensions, and layer structure;
- freeze the original encoder parameters in Stage 1;
- feed the 5G configuration tokens through the same pretrained encoder if its implementation supports the new token count.

### Token-count rule

Do **not** automatically map the 5G feature count to the original 4G feature count.

First inspect whether the original configuration encoder supports variable-length token sequences.

If it does:

```text
[B, N_5G_features, d_model]
→ pretrained configuration encoder directly
```

and no token-count mapping is needed.

Only introduce token resampling/aggregation if the actual original implementation requires a fixed token count.

---

## 7. Input Adapter

Use an input adapter only when there is a real interface mismatch between the new tokenizer and the pretrained configuration encoder.

Preferred logic:

```text
if tokenizer output dimension == pretrained encoder input dimension:
    no projection is needed
else:
    add a lightweight adapter
```

Typical adapter:

```text
LayerNorm
→ Linear
→ GELU
→ Linear
```

Resolved interface:

```text
5G tokenizer output:
[AUTO-DETECT]

Pretrained configuration encoder required input:
[AUTO-DETECT]

Chosen input adapter:
[AUTO-SELECT: none / normalization / linear projection / MLP]
```

Prefer the minimal required operation.

---

## 8. Token/Dimension Alignment After Configuration Encoder

Inspect the actual configuration encoder output and the input expected by the original fusion/cross-attention module.

```text
Configuration encoder output:
[AUTO-DETECT]

Cross-attention required configuration representation:
[AUTO-DETECT]

Chosen alignment:
[AUTO-SELECT: none / linear projection / MLP adapter / token resampler]
```

Rules:

- add an adapter only when dimensions do not match;
- add token resampling only when the original downstream code truly requires a fixed token count;
- do not insert unnecessary trainable layers.

---

## 9. KPI Branch

Reuse the original pretrained:

- KPI input embedding;
- temporal KPI encoder;
- inter-KPI attention;
- other KPI representation modules used in the original 4G pipeline.

### 9.1 Verify semantic alignment before reuse

Before feeding 5G KPIs into the pretrained KPI branch, verify:

```text
4G KPI names:
[AUTO-DETECT FROM ORIGINAL CODE/DATA CONFIG]

4G KPI order:
[AUTO-DETECT]

5G KPI names:
[AUTO-DETECT]

5G KPI order:
[AUTO-DETECT]

4G KPI preprocessing / normalization:
[AUTO-DETECT]

5G KPI preprocessing / normalization:
[AUTO-DETECT]
```

Do not assume that matching tensor dimensions imply matching KPI semantics.

Align KPIs by semantic/name correspondence, not only by position.

### 9.2 Missing KPI handling

If a KPI used by the 4G model is unavailable in 5G:

- preserve the original KPI slot/structure when required by the pretrained model;
- mark the unavailable KPI using a KPI availability mask;
- prevent the unavailable KPI from contributing to valid attention positions when required;
- exclude it from the reconstruction loss.

Conceptually:

```text
KPI availability mask:
available KPI   → 1
missing KPI     → 0
```

The pretrained KPI encoder architecture itself should remain unchanged in the main transfer experiment.

---

## 10. Cross-Attention

Reuse the original 4G pretrained cross-attention module.

### Main protocol

- load pretrained cross-attention weights;
- freeze original cross-attention parameters in Stage 1;
- preserve original query/key/value dimensions;
- satisfy interface differences using adapters outside the pretrained module.

Inspect:

```text
KPI query:
[AUTO-DETECT]

Configuration key:
[AUTO-DETECT]

Configuration value:
[AUTO-DETECT]
```

A different number of configuration tokens is acceptable if the original attention implementation supports variable key/value sequence length.

---

## 11. Reconstruction Head

Reuse the original 4G KPI reconstruction head when its output semantics are compatible.

Main protocol:

- load the pretrained reconstruction-head weights;
- freeze them in Stage 1;
- retain the original reconstruction objective;
- compute loss only on valid/available KPI channels and selected reconstruction-mask positions.

If an output-shape incompatibility exists because of KPI availability, handle it through masking/alignment before replacing the pretrained head.

---

## 12. Attribute Modality

The original 4G model contains an attribute modality, while the current 5G dataset does not provide the same attribute data.

Use a fixed modality availability mask:

```text
[configuration, attribute, KPI] = [1, 0, 1]
```

Main behavior:

- bypass the unavailable attribute encoder;
- keep its pretrained parameters unchanged;
- prevent the missing attribute representation from contributing to cross-modal fusion;
- use a missing-modality token only if the existing architecture requires one.

Do not move slow-varying 5G configuration settings into the attribute branch merely because they are static or slow-varying.

---

## 13. Overall 5G Transfer Architecture

Preferred architecture:

```text
5G Configuration
    ↓
Categorical index conversion / Numerical preprocessing
    ↓
New 5G Mixed-Feature Tokenizer
    ↓
Optional Input Adapter
    ↓
LTE-Pretrained Configuration Encoder
    ↓
Optional Representation Adapter
                                ┐
                                ├→ LTE-Pretrained Cross-Attention
5G KPI                          │
    ↓                           │
Pretrained KPI Embedding/Encoder
                                ┘
    ↓
LTE-Pretrained Reconstruction Head
    ↓
Masked KPI Reconstruction Loss
```

Attribute modality:

```text
unavailable → modality mask = 0 → bypass
```

---

## 14. Training Protocol

### Stage 0: Sanity Check

Before training:

1. successfully instantiate the original 4G model;
2. successfully load the 4G checkpoint;
3. report checkpoint/model key matching;
4. inspect one 5G batch;
5. resolve every implementation-dependent interface;
6. run at least one forward pass through the transfer model;
7. print/log key tensor shapes.

No large architectural change should be made before this step succeeds.

### Stage 1: Interface Adaptation

Train only newly introduced 5G-side modules:

- 5G categorical embeddings/tokenizer;
- 5G numerical tokenizer parameters;
- input adapter, if required;
- representation adapter, if required;
- token resampler, only if required.

Freeze:

- pretrained configuration encoder;
- pretrained KPI embedding;
- pretrained KPI encoder;
- pretrained inter-KPI attention;
- pretrained cross-attention;
- pretrained reconstruction head;
- attribute encoder.

Objective:

```text
original masked KPI reconstruction loss
```

This is the main transfer experiment.

### Stage 2: Optional Parameter-Efficient Adaptation

Only if Stage 1 is insufficient:

- continue training the new tokenizer/adapters;
- optionally add LoRA to the configuration encoder;
- optionally add LoRA to cross-attention;
- optionally train LayerNorm affine parameters.

Keep the main pretrained weights frozen.

### Stage 3: Optional Full Fine-Tuning Baseline

As an upper-bound/comparison experiment only:

- unfreeze the configuration encoder and/or cross-attention;
- optionally fine-tune the full compatible model.

This is not the main transfer protocol.

---

## 15. Reconstruction Loss

Retain the original 4G KPI reconstruction loss.

For available KPI channels:

\[
\mathcal{L}_{recon}
=
\frac{
\sum_{t,k} a_k r_{t,k}\ell(\hat{x}_{t,k},x_{t,k})
}{
\sum_{t,k} a_k r_{t,k}
}
\]

where:

- \(a_k\): KPI availability mask;
- \(r_{t,k}\): reconstruction masking indicator;
- \(\ell\): original reconstruction loss used in the 4G pipeline.

A missing 5G KPI has `a_k = 0` and does not contribute to the loss.

---

## 16. Follow the Existing 4G Training Pipeline

Except for the minimum changes required for 5G transfer, preserve the original 4G behavior for:

- batching;
- IterableDataset behavior;
- DDP logic;
- masking;
- forward-pass structure;
- KPI reconstruction;
- optimizer setup;
- validation;
- early stopping, if used;
- logging;
- checkpointing;
- random seeds;
- distributed synchronization;
- existing training utilities.

Reuse the original classes/functions/utilities wherever possible rather than reimplementing them.

---

## 17. Component-Level Plan

| Component | Initialization | Stage 1 |
|---|---|---|
| 5G categorical tokenizer | New | Train |
| 5G numerical tokenizer | New | Train |
| Input adapter | New only if required | Train if present |
| Pretrained configuration encoder | 4G checkpoint | Freeze |
| Token-count alignment/resampler | New only if required | Train if present |
| Representation adapter | New only if required | Train if present |
| KPI embedding | 4G checkpoint | Freeze |
| KPI encoder | 4G checkpoint | Freeze |
| Inter-KPI attention | 4G checkpoint | Freeze |
| Cross-attention | 4G checkpoint | Freeze |
| Reconstruction head | 4G checkpoint | Freeze |
| Attribute encoder | 4G checkpoint | Bypass/freeze |
| Modality mask | Fixed | Non-trainable |
| KPI availability mask | Derived from KPI availability | Non-trainable |

---

## 18. Required Runtime Diagnostics

At startup, print/log a concise transfer summary:

```text
4G checkpoint loaded: yes/no

Checkpoint matched keys:
[...]

Missing keys:
[...]

Unexpected keys:
[...]

5G categorical feature count:
[...]

5G numerical feature count:
[...]

Total 5G configuration token count:
[...]

Tokenizer output shape:
[...]

Configuration encoder input shape:
[...]

Configuration encoder output shape:
[...]

Cross-attention query/key/value shapes:
[...]

5G KPI order:
[...]

Missing KPI(s):
[...]

KPI availability mask:
[...]

Input adapter:
[none / description]

Representation adapter:
[none / description]

Token resampler:
[none / description]

Trainable parameter count:
[...]

Frozen parameter count:
[...]
```

These diagnostics should make it easy to verify that transfer is actually reusing the intended 4G pretrained backbone.

---

## 19. Important Implementation Rules

1. Do not hard-code example tensor dimensions from this document.
2. Do not assume a fixed 67→20 configuration mapping.
3. Do not add token resampling unless the actual 4G code requires a fixed token count.
4. Do not replace pretrained modules when a mask or lightweight adapter can solve the incompatibility.
5. Do not treat numerical configuration features as categorical.
6. Do not silently change numerical normalization.
7. Do not align KPIs only by tensor position; verify names/order/semantics.
8. Do not redesign the existing 4G training pipeline unnecessarily.
9. Prefer the smallest set of modifications required to make the pretrained 4G model operate on the 5G data.
10. Verify that the 4G checkpoint is genuinely loaded before starting 5G training.

---

## 20. Final Implementation Objective

The final implementation should demonstrate:

```text
4G pretrained backbone
+
new 5G configuration input interface
+
minimal lightweight alignment modules
+
original KPI reconstruction objective
→ 5G adaptation
```

The key question is whether knowledge learned during 4G pretraining can be reused on 5G with substantially fewer newly trained parameters than retraining the full model from scratch.
