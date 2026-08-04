# FT-Transformer Feature Tokenizer Notes for 5G Configuration Input

## Purpose

This note extracts only the FT-Transformer input-tokenization ideas needed for the 5G configuration pipeline.

Reference: **Gorishniy et al., "Revisiting Deep Learning Models for Tabular Data"**, Section 3.3 (FT-Transformer), especially the Feature Tokenizer.

The key idea is to convert **both numerical and categorical tabular features into tokens with the same embedding dimension**, then stack those feature tokens and feed them to a Transformer.

---

## 1. Input Structure

Assume one sample contains:

```text
x = (x_num, x_cat)
```

where:

- `x_num` contains the numerical features;
- `x_cat` contains the categorical features.

If there are:

```text
k_num numerical features
k_cat categorical features
```

then the total number of feature tokens is:

```text
k = k_num + k_cat
```

Each feature is converted into one token of dimension:

```text
d_model
```

The tokenizer output therefore has shape:

```text
[B, k, d_model]
```

where `B` is the batch size.

---

## 2. Numerical Feature Tokenization

For each numerical feature `j`, FT-Transformer learns a feature-specific vector:

```text
W_num[j] ∈ R^{d_model}
```

and a feature-specific bias:

```text
b_num[j] ∈ R^{d_model}
```

Given a scalar numerical value:

```text
x_num[j]
```

its feature token is:

```text
T_num[j] = b_num[j] + x_num[j] * W_num[j]
```

Therefore:

```text
scalar numerical value
        ↓
multiply by feature-specific learnable vector
        ↓
add feature-specific bias
        ↓
d_model-dimensional token
```

Important:

- Each numerical column has its own `W_num[j]`.
- Numerical features are **not** converted to categorical indices.
- Numerical features are **not** embedded through an embedding lookup table.
- The scalar value directly scales a learnable feature vector.

A simple PyTorch-style implementation is conceptually:

```python
# x_num: [B, N_num]

# numerical_weight:
# [N_num, d_model]

# numerical_bias:
# [N_num, d_model]

numerical_tokens = (
    x_num.unsqueeze(-1) * numerical_weight.unsqueeze(0)
    + numerical_bias.unsqueeze(0)
)

# output:
# [B, N_num, d_model]
```

---

## 3. Categorical Feature Tokenization

Each categorical feature has its own category vocabulary.

Before entering the model, raw categorical values should be converted into deterministic integer indices:

```text
raw categorical value
        ↓
category index
```

For categorical feature `j`, define its own embedding table:

```text
W_cat[j] ∈ R^{S_j × d_model}
```

where:

```text
S_j = number of categories for categorical feature j
```

and a feature-specific bias:

```text
b_cat[j] ∈ R^{d_model}
```

For category index `c_j`:

```text
T_cat[j] = b_cat[j] + Embedding_j(c_j)
```

Therefore:

```text
raw categorical value
        ↓
integer category index
        ↓
feature-specific embedding lookup
        ↓
add feature-specific bias
        ↓
d_model-dimensional token
```

Important:

- Each categorical column has its **own** vocabulary.
- Each categorical column has its **own** embedding table.
- The same category index in two different columns does not imply the same embedding.
- The category-to-index mapping must remain consistent across train/validation/test.
- Unknown/unseen categories should be handled explicitly, for example using a reserved `UNK` index.

A conceptual implementation is:

```python
categorical_tokens = []

for j, embedding_layer in enumerate(category_embeddings):
    token_j = embedding_layer(x_cat[:, j])
    token_j = token_j + categorical_bias[j]
    categorical_tokens.append(token_j)

categorical_tokens = torch.stack(categorical_tokens, dim=1)

# [B, N_cat, d_model]
```

---

## 4. Combining Numerical and Categorical Tokens

After both feature types have been converted into the same embedding dimension:

```text
numerical_tokens:
[B, N_num, d_model]

categorical_tokens:
[B, N_cat, d_model]
```

stack/concatenate them along the feature-token dimension:

```python
feature_tokens = torch.cat(
    [numerical_tokens, categorical_tokens],
    dim=1
)
```

giving:

```text
[B, N_num + N_cat, d_model]
```

Conceptually:

```text
Numerical features ─→ Numerical Tokenizer ─┐
                                           │
                                           ├→ Feature Tokens
                                           │   [B, N_features, d_model]
Categorical features → Category Indices ───┤
                     → Embedding Lookups ──┘
```

The Transformer then operates over these **feature tokens**.

---

## 5. Relation to the 5G Transfer Pipeline

For the 5G configuration input, use the FT-Transformer tokenization idea only for the **new 5G configuration tokenizer**.

Conceptually:

```text
5G categorical configuration features
    ↓
raw value → category index → feature-specific embedding
                                             ┐
                                             │
                                             ├→ stack feature tokens
                                             │
5G numerical configuration features          │
    ↓                                        │
scalar × feature-specific learnable vector ──┘
    ↓
[B, N_5G_features, d_model]
    ↓
optional adapter, only if actually needed
    ↓
pretrained 4G configuration encoder
```

The output embedding dimension should be selected to match the actual input dimension expected by the pretrained 4G configuration encoder whenever possible.

Do **not** assume that the 5G token count must equal the original 4G token count.

If the pretrained Transformer supports variable sequence length, keep the native number of 5G feature tokens.

---

## 6. Numerical Preprocessing

The paper treats preprocessing as important, but the exact numerical preprocessing is dataset-dependent rather than part of the Feature Tokenizer equation itself.

For the current 5G implementation:

1. inspect the existing preprocessing first;
2. do not silently introduce a new normalization scheme;
3. if normalization/transformation is needed, fit it using the training split only;
4. store and reuse the same preprocessing parameters for validation/test.

The tokenization operation itself remains:

```text
T_num[j] = b_num[j] + x_num[j] * W_num[j]
```

using the numerical value after the chosen preprocessing.

---

## 7. Implementation Checklist for Copilot

Before implementing the tokenizer, determine:

```text
Categorical-column list:
[CATEGORICAL_COLUMNS_LIST_PATH]

Numerical-column list:
[NUMERICAL_COLUMNS_LIST_PATH]

Categorical-value/category-mapping CSV:
[CATEGORICAL_VALUES_CSV_PATH]

Number of categorical features:
[AUTO-DETECT]

Number of numerical features:
[AUTO-DETECT]

d_model expected by the pretrained 4G configuration encoder:
[AUTO-DETECT FROM ORIGINAL 4G MODEL]
```

Then implement:

```text
categorical raw values
→ stable integer indices
→ per-feature embedding tables
→ categorical tokens

numerical values
→ per-feature learnable vectors
→ numerical tokens

categorical + numerical tokens
→ [B, N_5G_features, d_model]
```

Prefer the smallest possible change to the existing 4G pipeline. This tokenizer should replace/adapt only the **input representation of 5G configuration features**; the pretrained downstream configuration encoder should be reused whenever its interface is compatible.

---

## 8. Minimal Mathematical Summary

For numerical feature `j`:

\[
T_j^{(\mathrm{num})}
=
b_j^{(\mathrm{num})}
+
x_j^{(\mathrm{num})} W_j^{(\mathrm{num})}
\]

For categorical feature `j`:

\[
T_j^{(\mathrm{cat})}
=
b_j^{(\mathrm{cat})}
+
\mathrm{Embedding}_j(x_j^{(\mathrm{cat})})
\]

Finally:

\[
T =
\mathrm{stack}
\left(
T_1^{(\mathrm{num})}, \ldots,
T_{k_{\mathrm{num}}}^{(\mathrm{num})},
T_1^{(\mathrm{cat})}, \ldots,
T_{k_{\mathrm{cat}}}^{(\mathrm{cat})}
\right)
\]

with:

```text
T ∈ R^{B × (N_num + N_cat) × d_model}
```
