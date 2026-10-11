# Fitting guide

How to choose a pipeline configuration that reaches a speed and an accuracy on a device, and what to change when a run misses a target. The numbers are those of the model zoo page: reference device with 1 CPU core and 512 MB, 1 thread. This page is written by `tools/zoo_report.py` from the same measurements.

## The four settings

- `model`: the network that classifies the picture. It decides most of the speed, the accuracy and the memory.
- `precision`: `fp32` is the model as it was trained. `int8` is the same model with 8-bit integers: smaller, usually faster, and for some models much less accurate.
- `input_size`: the side of the picture given to the model: 224, 192, 160 or 128 pixels. Smaller is faster and less accurate.
- `threads`: how many threads compute. It helps only on a device with more than one core.

## Start from the accuracy

Accuracy is the harder target: few configurations reach a high one, and no setting buys accuracy back cheaply. So first keep only the configurations that are accurate enough, then take the fastest of them that is fast enough.

This page has a list for every level of accuracy from 50% to 85% in steps of 5, and for 86% and 87%: "Configurations with at least 80% accuracy" and so on. Use the list of the target, or of the next level up. The best accuracy in the zoo is 87.5%: a higher target cannot be met.

## Configurations with at least 87% accuracy

The fastest configurations that reach 87% accuracy or more, on the reference device with 1 core, fastest first:

- model `efficientnet_b0`, precision `fp32`, input_size 224: 58 images/s, 87.5% accuracy, 91 MB
- model `resnet50`, precision `int8`, input_size 224: 41 images/s, 87.0% accuracy, 68 MB

## Configurations with at least 86% accuracy

The fastest configurations that reach 86% accuracy or more, on the reference device with 1 core, fastest first:

- model `efficientnet_b0`, precision `fp32`, input_size 224: 58 images/s, 87.5% accuracy, 91 MB
- model `resnet50`, precision `int8`, input_size 224: 41 images/s, 87.0% accuracy, 68 MB
- model `resnet50`, precision `fp32`, input_size 224: 14 images/s, 86.0% accuracy, 243 MB

## Configurations with at least 85% accuracy

The fastest configurations that reach 85% accuracy or more, on the reference device with 1 core, fastest first:

- model `efficientnet_b0`, precision `fp32`, input_size 192: 75 images/s, 85.0% accuracy, 78 MB
- model `efficientnet_b0`, precision `fp32`, input_size 224: 58 images/s, 87.5% accuracy, 91 MB
- model `resnet50`, precision `int8`, input_size 224: 41 images/s, 87.0% accuracy, 68 MB
- model `resnet50`, precision `fp32`, input_size 224: 14 images/s, 86.0% accuracy, 243 MB

## Configurations with at least 80% accuracy

The fastest configurations that reach 80% accuracy or more, on the reference device with 1 core, fastest first:

- model `mobilenet_v3_small`, precision `fp32`, input_size 192: 272 images/s, 80.5% accuracy, 46 MB
- model `mobilenet_v3_small`, precision `fp32`, input_size 224: 264 images/s, 82.5% accuracy, 47 MB
- model `resnet18`, precision `int8`, input_size 192: 106 images/s, 80.0% accuracy, 46 MB
- model `resnet50`, precision `int8`, input_size 128: 99 images/s, 82.0% accuracy, 62 MB
- model `efficientnet_b0`, precision `fp32`, input_size 160: 98 images/s, 82.5% accuracy, 80 MB
- model `resnet18`, precision `int8`, input_size 224: 85 images/s, 82.5% accuracy, 48 MB

## Configurations with at least 75% accuracy

The fastest configurations that reach 75% accuracy or more, on the reference device with 1 core, fastest first:

- model `mobilenet_v3_small`, precision `fp32`, input_size 192: 272 images/s, 80.5% accuracy, 46 MB
- model `mobilenet_v3_small`, precision `fp32`, input_size 224: 264 images/s, 82.5% accuracy, 47 MB
- model `mobilenet_v2`, precision `int8`, input_size 224: 188 images/s, 75.0% accuracy, 39 MB
- model `efficientnet_b0`, precision `fp32`, input_size 128: 140 images/s, 77.5% accuracy, 75 MB
- model `mobilenet_v2`, precision `fp32`, input_size 224: 114 images/s, 75.5% accuracy, 57 MB
- model `resnet18`, precision `int8`, input_size 192: 106 images/s, 80.0% accuracy, 46 MB

## Configurations with at least 70% accuracy

The fastest configurations that reach 70% accuracy or more, on the reference device with 1 core, fastest first:

- model `mobilenet_v2`, precision `int8`, input_size 160: 275 images/s, 73.5% accuracy, 36 MB
- model `mobilenet_v3_small`, precision `fp32`, input_size 192: 272 images/s, 80.5% accuracy, 46 MB
- model `mobilenet_v3_small`, precision `fp32`, input_size 224: 264 images/s, 82.5% accuracy, 47 MB
- model `mobilenet_v2`, precision `fp32`, input_size 128: 246 images/s, 70.5% accuracy, 55 MB
- model `mobilenet_v2`, precision `int8`, input_size 192: 218 images/s, 74.5% accuracy, 36 MB
- model `mobilenet_v2`, precision `int8`, input_size 224: 188 images/s, 75.0% accuracy, 39 MB

## Configurations with at least 65% accuracy

The fastest configurations that reach 65% accuracy or more, on the reference device with 1 core, fastest first:

- model `mobilenet_v3_small`, precision `fp32`, input_size 160: 336 images/s, 68.5% accuracy, 45 MB
- model `mobilenet_v2`, precision `int8`, input_size 160: 275 images/s, 73.5% accuracy, 36 MB
- model `mobilenet_v3_small`, precision `fp32`, input_size 192: 272 images/s, 80.5% accuracy, 46 MB
- model `mobilenet_v3_small`, precision `fp32`, input_size 224: 264 images/s, 82.5% accuracy, 47 MB
- model `mobilenet_v2`, precision `fp32`, input_size 128: 246 images/s, 70.5% accuracy, 55 MB
- model `mobilenet_v2`, precision `int8`, input_size 192: 218 images/s, 74.5% accuracy, 36 MB

## Configurations with at least 60% accuracy

The fastest configurations that reach 60% accuracy or more, on the reference device with 1 core, fastest first:

- model `mobilenet_v3_small`, precision `fp32`, input_size 160: 336 images/s, 68.5% accuracy, 45 MB
- model `mobilenet_v2`, precision `int8`, input_size 160: 275 images/s, 73.5% accuracy, 36 MB
- model `mobilenet_v3_small`, precision `fp32`, input_size 192: 272 images/s, 80.5% accuracy, 46 MB
- model `mobilenet_v3_small`, precision `fp32`, input_size 224: 264 images/s, 82.5% accuracy, 47 MB
- model `mobilenet_v2`, precision `fp32`, input_size 128: 246 images/s, 70.5% accuracy, 55 MB
- model `mobilenet_v2`, precision `int8`, input_size 192: 218 images/s, 74.5% accuracy, 36 MB

## Configurations with at least 55% accuracy

The fastest configurations that reach 55% accuracy or more, on the reference device with 1 core, fastest first:

- model `mobilenet_v3_small`, precision `fp32`, input_size 160: 336 images/s, 68.5% accuracy, 45 MB
- model `mobilenet_v2`, precision `int8`, input_size 160: 275 images/s, 73.5% accuracy, 36 MB
- model `mobilenet_v3_small`, precision `fp32`, input_size 192: 272 images/s, 80.5% accuracy, 46 MB
- model `mobilenet_v3_small`, precision `fp32`, input_size 224: 264 images/s, 82.5% accuracy, 47 MB
- model `mobilenet_v2`, precision `fp32`, input_size 128: 246 images/s, 70.5% accuracy, 55 MB
- model `mobilenet_v2`, precision `int8`, input_size 192: 218 images/s, 74.5% accuracy, 36 MB

## Configurations with at least 50% accuracy

The fastest configurations that reach 50% accuracy or more, on the reference device with 1 core, fastest first:

- model `mobilenet_v3_small`, precision `fp32`, input_size 128: 428 images/s, 52.5% accuracy, 46 MB
- model `mobilenet_v3_small`, precision `fp32`, input_size 160: 336 images/s, 68.5% accuracy, 45 MB
- model `mobilenet_v2`, precision `int8`, input_size 160: 275 images/s, 73.5% accuracy, 36 MB
- model `mobilenet_v3_small`, precision `fp32`, input_size 192: 272 images/s, 80.5% accuracy, 46 MB
- model `mobilenet_v3_small`, precision `fp32`, input_size 224: 264 images/s, 82.5% accuracy, 47 MB
- model `mobilenet_v2`, precision `fp32`, input_size 128: 246 images/s, 70.5% accuracy, 55 MB

## When the pipeline is too slow

Try these in order, and stop at the first that is enough.

1. Use int8, if the model is `mobilenet_v2`, `resnet18`, `resnet50`. It is the only change that costs almost no accuracy: `mobilenet_v2` becomes 1.6 times faster, `resnet18` becomes 2.8 times faster, `resnet50` becomes 3.1 times faster.
2. Lower `input_size` by one step. From 224 to 192 a pipeline is about 1.2 times faster and loses from 0.5 to 2.5 points of accuracy.
3. Take a faster model that is still accurate enough: see the list of configurations for the accuracy of the target.
4. On a device with 2 cores, set `threads` to 2.

Never use int8 with `mobilenet_v3_small` or `efficientnet_b0` to gain speed: the accuracy collapses.

## When the accuracy is too low

1. Check the precision first. `mobilenet_v3_small` and `efficientnet_b0` are ruined by int8 (1.5% instead of 82.5%, 34.0% instead of 87.5%): with these two use fp32.
2. Raise `input_size` towards 224. Every model is most accurate at 224.
3. Take a more accurate model. The most accurate are `efficientnet_b0` fp32 at 224 (58 images/s, 87.5%); `resnet50` int8 at 224 (41 images/s, 87.0%); `resnet50` fp32 at 224 (14 images/s, 86.0%).
4. If the target is above 87.5%, no configuration reaches it: say so instead of trying.

## What int8 changes

int8 stores the weights and the intermediate values of the model as 8-bit integers instead of 32-bit numbers. The file is about a quarter of the size, the model needs less memory, and on a CPU the arithmetic is faster.

| model | speed in int8 | accuracy fp32 → int8 | memory fp32 → int8 |
|---|---|---|---|
| mobilenet_v3_small | 1.1 times | 82.5% → 1.5% | 47 → 36 MB |
| mobilenet_v2 | 1.6 times | 75.5% → 75.0% | 57 → 39 MB |
| efficientnet_b0 | 1.7 times | 87.5% → 34.0% | 91 → 48 MB |
| resnet18 | 2.8 times | 81.0% → 82.5% | 121 → 48 MB |
| resnet50 | 3.1 times | 86.0% → 87.0% | 243 → 68 MB |

The models were quantized after training, with ranges measured on 60 pictures. `mobilenet_v3_small` and `efficientnet_b0` do not survive this simple method. Why was not investigated in this project.

## What a smaller input size changes

A smaller picture has fewer pixels to compute, so the speed grows roughly with the pixels saved: 160 pixels is about half the work of 224. The price in accuracy depends on the model. Accuracy at 224 → 192 → 160 → 128 pixels, in the precision each model should be used in:

- `mobilenet_v3_small` fp32: 82.5 → 80.5 → 68.5 → 52.5 %, at 263.5 → 272.2 → 336.5 → 427.6 images/s
- `mobilenet_v2` int8: 75 → 74.5 → 73.5 → 46.5 %, at 187.5 → 218.2 → 275.1 → 381.8 images/s
- `efficientnet_b0` fp32: 87.5 → 85 → 82.5 → 77.5 %, at 58 → 74.6 → 98.3 → 140 images/s
- `resnet18` int8: 82.5 → 80 → 71.5 → 62.5 %, at 84.6 → 105.8 → 137.5 → 190.7 images/s
- `resnet50` int8: 87 → 84.5 → 84.5 → 82 %, at 41.3 → 53.3 → 69.9 → 98.8 images/s

## Threads and CPU cores

Use as many threads as the device has whole cores, and never more. One thread is right for a device with one core or less: with more, the threads take turns on the same core and the pipeline gets slower. On 1 core, `mobilenet_v2` fp32 runs at 114 images/s with 1 thread, 84 with 2 and 56 with 4; `resnet50` int8 at 41, 34 and 21.

On a device with 2 cores, 2 threads are the best choice: `resnet50` fp32 runs at 13.2 images/s with 1 thread, 24.7 with 2 and 18.5 with 4; `efficientnet_b0` fp32 at 58, 92 and 60. Two cores do not double the speed: expect from 1.5 to 1.9 times.

## Half a core, two cores

Speed follows the CPU the device has. On half a core every configuration runs at about 0.49 times its speed on one core. Accuracy does not depend on the device: the same configuration gives the same answers everywhere.

So a target of 30 images/s on half a core needs a configuration that reaches about 61 on the reference device.

## When a run goes out of memory

The pipeline needed more memory than the device has and was stopped. Memory depends on the model and the precision, and hardly on the input size, so a smaller picture does not fix it. Use int8, or a smaller model.

On the device with 128 MB these go out of memory: `resnet18` fp32, `resnet50` fp32. Everything else fits. On 512 MB and more, every configuration fits.
