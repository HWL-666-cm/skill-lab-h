## 3.1 Procedure

First we set a learning rate of 1e-4, then a batch size of 256, and train 100 epochs.

## 3.2 Setup and data

We use 8 GPUs with the seed 42 and resize every image to a resolution of 512.

## 3.3 Baseline

Compared with the released checkpoint at the same budget.

## 3.4 Limitations

It fails when the batch is smaller than 8, because the gradient estimate becomes too noisy.
