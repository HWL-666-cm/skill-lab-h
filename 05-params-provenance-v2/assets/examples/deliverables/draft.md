## 3.1 Procedure

First we set a learning rate of 1e-4, then a batch size of 256, and train 100 epochs.

## 3.2 Setup and data

We use 8 GPUs with the seed 42 and resize every image to a resolution of 512.

## 3.3 Baseline

Compared with the released checkpoint at the same budget.

## 3.4 Reproducibility

We run in Python 3 with the environment, launched by `python train.py`; the data is downloaded from the official site.

## 3.5 Limitations

It fails when the batch is smaller than 8, because the gradient estimate becomes too noisy.
