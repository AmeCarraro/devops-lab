# Model zoo

The zoo is the set of image classification models a pipeline can use: five models, each in two precisions, `fp32` and `int8`, at four input sizes. This page says how fast, how accurate and how large each of them is. It is written by `tools/zoo_report.py` from measurements: to change a number, measure again.

## How the numbers were measured

Every number in this page was measured in the sandbox on the reference device: 1 CPU core, 512 MB of memory, 1 thread. Speed is images per second over the 200 evaluation pictures, from the file to the answer. Accuracy is the share of those pictures classified correctly among the 1000 classes of ImageNet. Memory is the most the pipeline held and could not give back.

The measurements were made once each, on 2026-10-10, on the laptop the project is developed on. Another machine gives other speeds, and a second run on the same machine differs by a few percent. What carries over is the order of the configurations and the size of the gaps between them.

## Which model is the fastest

At 224 pixels in fp32, from the fastest to the slowest: `mobilenet_v3_small` (264 images/s), `mobilenet_v2` (114 images/s), `efficientnet_b0` (58 images/s), `resnet18` (30 images/s), `resnet50` (14 images/s).

In int8 the two resnets gain the most: `mobilenet_v3_small` (294), `mobilenet_v2` (188), `efficientnet_b0` (98), `resnet18` (85), `resnet50` (41). Speed alone is not enough to choose: two of these models lose their accuracy in int8.

## Which model is the most accurate

At 224 pixels, from the most accurate: `efficientnet_b0` fp32 (87.5%), `resnet50` int8 (87.0%), `resnet50` fp32 (86.0%), `resnet18` int8 (82.5%), `mobilenet_v3_small` fp32 (82.5%), `resnet18` fp32 (81.0%), `mobilenet_v2` fp32 (75.5%), `mobilenet_v2` int8 (75.0%), `efficientnet_b0` int8 (34.0%), `mobilenet_v3_small` int8 (1.5%).

No usable configuration of the zoo is above 87.5% on the evaluation pictures: a target higher than that cannot be met.

## Models that must not be used in int8

Quantization ruins two models of the zoo: `mobilenet_v3_small` falls from 82.5% to 1.5% and `efficientnet_b0` falls from 87.5% to 34.0%. Use these two in fp32 only.

The other three keep their accuracy in int8 at 224 pixels: `mobilenet_v2` (75.5% in fp32, 75.0% in int8), `resnet18` (81.0% in fp32, 82.5% in int8), `resnet50` (86.0% in fp32, 87.0% in int8).

## mobilenet_v3_small

The smallest and fastest model of the zoo. Use it when speed matters most. It has 2.5 million parameters; the file is 10.2 MB in fp32 and 2.9 MB in int8.

| precision | input size | images/s | accuracy | memory |
|---|---|---|---|---|
| fp32 | 224 | 263.5 | 82.5% | 47 MB |
| fp32 | 192 | 272.2 | 80.5% | 46 MB |
| fp32 | 160 | 336.5 | 68.5% | 45 MB |
| fp32 | 128 | 427.6 | 52.5% | 46 MB |
| int8 | 224 | 294.4 | 1.5% | 36 MB |
| int8 | 192 | 281.6 | 1.5% | 35 MB |
| int8 | 160 | 379.0 | 1.5% | 35 MB |
| int8 | 128 | 515.2 | 1.5% | 35 MB |

## mobilenet_v2

A small model that is fast in both precisions. It is the least accurate of the zoo. It has 3.5 million parameters; the file is 14.0 MB in fp32 and 3.9 MB in int8.

| precision | input size | images/s | accuracy | memory |
|---|---|---|---|---|
| fp32 | 224 | 114.0 | 75.5% | 57 MB |
| fp32 | 192 | 136.3 | 74.5% | 55 MB |
| fp32 | 160 | 179.4 | 71.5% | 57 MB |
| fp32 | 128 | 246.3 | 70.5% | 55 MB |
| int8 | 224 | 187.5 | 75.0% | 39 MB |
| int8 | 192 | 218.2 | 74.5% | 36 MB |
| int8 | 160 | 275.1 | 73.5% | 36 MB |
| int8 | 128 | 381.8 | 46.5% | 35 MB |

## efficientnet_b0

The most accurate model of the zoo, and it needs less memory than the resnets. It is slower than the two mobilenets. It has 5.3 million parameters; the file is 21.1 MB in fp32 and 6.2 MB in int8.

| precision | input size | images/s | accuracy | memory |
|---|---|---|---|---|
| fp32 | 224 | 58.0 | 87.5% | 91 MB |
| fp32 | 192 | 74.6 | 85.0% | 78 MB |
| fp32 | 160 | 98.3 | 82.5% | 80 MB |
| fp32 | 128 | 140.0 | 77.5% | 75 MB |
| int8 | 224 | 97.9 | 34.0% | 48 MB |
| int8 | 192 | 119.5 | 31.5% | 45 MB |
| int8 | 160 | 155.2 | 25.5% | 44 MB |
| int8 | 128 | 216.3 | 18.5% | 42 MB |

## resnet18

A mid-size model. In fp32 it is slow for its accuracy; in int8 it is almost three times faster and just as accurate. It has 11.7 million parameters; the file is 46.7 MB in fp32 and 11.8 MB in int8.

| precision | input size | images/s | accuracy | memory |
|---|---|---|---|---|
| fp32 | 224 | 30.2 | 81.0% | 121 MB |
| fp32 | 192 | 38.5 | 78.5% | 119 MB |
| fp32 | 160 | 54.1 | 73.0% | 117 MB |
| fp32 | 128 | 78.2 | 65.5% | 108 MB |
| int8 | 224 | 84.6 | 82.5% | 48 MB |
| int8 | 192 | 105.8 | 80.0% | 46 MB |
| int8 | 160 | 137.5 | 71.5% | 45 MB |
| int8 | 128 | 190.7 | 62.5% | 44 MB |

## resnet50

The largest model: accurate, slow and hungry for memory in fp32. In int8 it is three times faster and needs less than a third of the memory. It has 25.6 million parameters; the file is 102.1 MB in fp32 and 26.1 MB in int8.

| precision | input size | images/s | accuracy | memory |
|---|---|---|---|---|
| fp32 | 224 | 13.5 | 86.0% | 243 MB |
| fp32 | 192 | 17.8 | 84.5% | 226 MB |
| fp32 | 160 | 24.9 | 84.5% | 242 MB |
| fp32 | 128 | 35.5 | 84.5% | 213 MB |
| int8 | 224 | 41.3 | 87.0% | 68 MB |
| int8 | 192 | 53.3 | 84.5% | 65 MB |
| int8 | 160 | 69.9 | 84.5% | 61 MB |
| int8 | 128 | 98.8 | 82.0% | 62 MB |

## Memory each model needs

Memory depends on the model and the precision, and hardly on the input size. At 224 pixels:

| model | fp32 | int8 |
|---|---|---|
| mobilenet_v3_small | 47 MB | 36 MB |
| mobilenet_v2 | 57 MB | 39 MB |
| efficientnet_b0 | 91 MB | 48 MB |
| resnet18 | 121 MB | 48 MB |
| resnet50 | 243 MB | 68 MB |

On the smallest device, which has 128 MB, these go out of memory and are stopped: `resnet18` fp32, `resnet50` fp32. These fit: `mobilenet_v3_small` fp32, `mobilenet_v3_small` int8, `mobilenet_v2` fp32, `mobilenet_v2` int8, `efficientnet_b0` fp32, `efficientnet_b0` int8, `resnet18` int8, `resnet50` int8.
