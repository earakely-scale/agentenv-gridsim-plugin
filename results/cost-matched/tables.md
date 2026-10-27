### 1. Foresight, eval-2025 (200 tasks, 157 days; the 4B is run 3 final)

| model | R | 95% CI | x = (R − 0.2)/0.8 | valid | feasible | cost per task | output tokens per task |
|---|---|---|---|---|---|---|---|
| **trained 4B, sampled** | **0.885** | [0.856, 0.911] | 0.856 | 99.5% | 89.5% | $0.00013 | 368 |
| trained 4B, greedy decoding | 0.886 | [0.856, 0.913] | 0.857 | 100.0% | 88.0% | $0.00013 | 369 |
| **GPT-6 Luna, effort high** | **0.913** | [0.881, 0.942] | 0.891 | 96.5% | 96.0% | $0.0029 | 5,585 |
| GPT-6 Luna, effort low | 0.768 | [0.726, 0.807] | 0.710 | 99.5% | 86.5% | $0.00060 | 1,031 |
| GPT-6.1 Sol, effort high | 1.000 | [1.000, 1.000] | 1.000 | 100.0% | 100.0% | $0.0120 | 1,021 |

| paired gap | mean [day-block 95% CI] | shown | 4B or first model ahead / level | days ahead |
|---|---|---|---|---|
| **trained 4B, sampled − GPT-6 Luna, effort high** | −0.028 [−0.067, +0.011] | not shown | 30% / 20% | 48/157 |
| trained 4B, greedy decoding − GPT-6 Luna, effort high | −0.027 [−0.070, +0.015] | not shown | 30% / 22% | 51/157 |
| trained 4B, sampled − GPT-6 Luna, effort low | +0.117 [+0.072, +0.164] | above 0 | 63% / 12% | 101/157 |
| trained 4B, greedy decoding − GPT-6 Luna, effort low | +0.118 [+0.074, +0.162] | above 0 | 65% / 12% | 106/157 |
| trained 4B, sampled − GPT-6.1 Sol, effort high | −0.115 [−0.144, −0.088] | below 0 | 0% / 37% | 0/157 |
| trained 4B, greedy decoding − GPT-6.1 Sol, effort high | −0.114 [−0.144, −0.087] | below 0 | 0% / 39% | 0/157 |
| GPT-6 Luna, effort high − GPT-6.1 Sol, effort high | −0.087 [−0.119, −0.058] | below 0 | 0% / 50% | 1/157 |
| GPT-6 Luna, effort low − GPT-6.1 Sol, effort high | −0.232 [−0.274, −0.193] | below 0 | 0% / 13% | 0/157 |
| GPT-6 Luna, effort low − GPT-6 Luna, effort high | −0.145 [−0.197, −0.095] | below 0 | 16% / 12% | 24/157 |

### 2. Foresight, fresh 10-18..27 (362 tasks, 10 days; the 4B is run 3 final)

| model | R | 95% CI | x = (R − 0.2)/0.8 | valid | feasible | cost per task | output tokens per task |
|---|---|---|---|---|---|---|---|
| **trained 4B, sampled** | **0.855** | [0.839, 0.872] | 0.819 | 99.5% | 90.3% | $0.00014 | 367 |
| trained 4B, greedy decoding | 0.860 | [0.825, 0.892] | 0.825 | 99.7% | 90.1% | $0.00014 | 368 |
| **GPT-6 Luna, effort high** | **0.958** | [0.945, 0.970] | 0.947 | 99.5% | 98.6% | $0.0024 | 4,562 |
| GPT-6 Luna, effort low | 0.796 | [0.764, 0.829] | 0.746 | 99.5% | 87.3% | $0.00058 | 993 |
| GPT-6.1 Sol, effort high | 1.000 | [1.000, 1.000] | 1.000 | 100.0% | 100.0% | $0.0103 | 851 |

| paired gap | mean [day-block 95% CI] | shown | 4B or first model ahead / level | days ahead |
|---|---|---|---|---|
| **trained 4B, sampled − GPT-6 Luna, effort high** | −0.102 [−0.123, −0.083] | below 0 | 20% / 27% | 0/10 |
| trained 4B, greedy decoding − GPT-6 Luna, effort high | −0.098 [−0.140, −0.059] | below 0 | 20% / 27% | 0/10 |
| trained 4B, sampled − GPT-6 Luna, effort low | +0.059 [+0.035, +0.083] | above 0 | 56% / 15% | 10/10 |
| trained 4B, greedy decoding − GPT-6 Luna, effort low | +0.063 [+0.021, +0.105] | above 0 | 58% / 14% | 9/10 |
| trained 4B, sampled − GPT-6.1 Sol, effort high | −0.145 [−0.161, −0.128] | below 0 | 0% / 33% | 0/10 |
| trained 4B, greedy decoding − GPT-6.1 Sol, effort high | −0.140 [−0.175, −0.108] | below 0 | 0% / 36% | 0/10 |
| GPT-6 Luna, effort high − GPT-6.1 Sol, effort high | −0.042 [−0.055, −0.030] | below 0 | 0% / 62% | 0/10 |
| GPT-6 Luna, effort low − GPT-6.1 Sol, effort high | −0.203 [−0.236, −0.171] | below 0 | 0% / 15% | 0/10 |
| GPT-6 Luna, effort low − GPT-6 Luna, effort high | −0.161 [−0.190, −0.132] | below 0 | 10% / 15% | 0/10 |

### 3a. Blind, eval-2025 (300 tasks, 191 days; the 4B is run 4 final)

| model | C | 95% CI | R (anchor scale) | valid | feasible | cost per task | output tokens per task |
|---|---|---|---|---|---|---|---|
| **trained 4B, sampled** | **0.828** | [0.801, 0.853] | 0.879 | 100.0% | 90.0% | $0.00048 | 420 |
| trained 4B, greedy decoding | 0.831 | [0.806, 0.854] | 0.882 | 100.0% | 90.3% | $0.00048 | 421 |
| **GPT-6 Luna, effort high** | **0.829** | [0.806, 0.850] | 0.882 | 99.0% | 98.0% | $0.0020 | 3,672 |
| GPT-6 Luna, effort low | 0.682 | [0.651, 0.713] | 0.729 | 99.7% | 85.0% | $0.00053 | 683 |
| GPT-6.1 Sol, effort high | 0.903 | [0.883, 0.921] | 0.960 | 99.0% | 99.0% | $0.0158 | 1,211 |

| paired gap | mean [day-block 95% CI] | shown | 4B or first model ahead / level | days ahead |
|---|---|---|---|---|
| **trained 4B, sampled − GPT-6 Luna, effort high** | −0.001 [−0.030, +0.028] | not shown | 50% / 9% | 102/191 |
| trained 4B, greedy decoding − GPT-6 Luna, effort high | +0.002 [−0.025, +0.028] | not shown | 48% / 9% | 98/191 |
| trained 4B, sampled − GPT-6 Luna, effort low | +0.146 [+0.108, +0.184] | above 0 | 69% / 4% | 145/191 |
| trained 4B, greedy decoding − GPT-6 Luna, effort low | +0.149 [+0.111, +0.186] | above 0 | 68% / 4% | 136/191 |
| trained 4B, sampled − GPT-6.1 Sol, effort high | −0.075 [−0.101, −0.050] | below 0 | 26% / 19% | 48/191 |
| trained 4B, greedy decoding − GPT-6.1 Sol, effort high | −0.072 [−0.097, −0.049] | below 0 | 24% / 20% | 39/191 |
| GPT-6 Luna, effort high − GPT-6.1 Sol, effort high | −0.074 [−0.095, −0.054] | below 0 | 20% / 19% | 33/191 |
| GPT-6 Luna, effort low − GPT-6.1 Sol, effort high | −0.221 [−0.252, −0.191] | below 0 | 10% / 7% | 17/191 |
| GPT-6 Luna, effort low − GPT-6 Luna, effort high | −0.147 [−0.179, −0.115] | below 0 | 22% / 8% | 37/191 |

### 3b. Blind, fresh 10-18..27 (331 tasks, 10 days; the 4B is run 4 final)

| model | C | 95% CI | R (anchor scale) | valid | feasible | cost per task | output tokens per task |
|---|---|---|---|---|---|---|---|
| **trained 4B, sampled** | **0.841** | [0.793, 0.873] | 0.898 | 100.0% | 91.8% | $0.00047 | 429 |
| trained 4B, greedy decoding | 0.840 | [0.792, 0.875] | 0.896 | 100.0% | 90.3% | $0.00048 | 430 |
| **GPT-6 Luna, effort high** | **0.836** | [0.800, 0.861] | 0.887 | 98.8% | 98.5% | $0.0020 | 3,656 |
| GPT-6 Luna, effort low | 0.690 | [0.657, 0.723] | 0.736 | 98.2% | 83.7% | $0.00052 | 678 |
| GPT-6.1 Sol, effort high | 0.913 | [0.864, 0.949] | 0.969 | 99.1% | 99.1% | $0.0158 | 1,216 |

| paired gap | mean [day-block 95% CI] | shown | 4B or first model ahead / level | days ahead |
|---|---|---|---|---|
| **trained 4B, sampled − GPT-6 Luna, effort high** | +0.005 [−0.036, +0.044] | not shown | 54% / 6% | 5/10 |
| trained 4B, greedy decoding − GPT-6 Luna, effort high | +0.004 [−0.036, +0.037] | not shown | 53% / 6% | 5/10 |
| trained 4B, sampled − GPT-6 Luna, effort low | +0.151 [+0.085, +0.197] | above 0 | 72% / 3% | 9/10 |
| trained 4B, greedy decoding − GPT-6 Luna, effort low | +0.150 [+0.081, +0.200] | above 0 | 71% / 2% | 9/10 |
| trained 4B, sampled − GPT-6.1 Sol, effort high | −0.072 [−0.090, −0.050] | below 0 | 26% / 9% | 0/10 |
| trained 4B, greedy decoding − GPT-6.1 Sol, effort high | −0.073 [−0.090, −0.057] | below 0 | 25% / 11% | 0/10 |
| GPT-6 Luna, effort high − GPT-6.1 Sol, effort high | −0.077 [−0.114, −0.036] | below 0 | 21% / 8% | 2/10 |
| GPT-6 Luna, effort low − GPT-6.1 Sol, effort high | −0.223 [−0.281, −0.150] | below 0 | 14% / 2% | 0/10 |
| GPT-6 Luna, effort low − GPT-6 Luna, effort high | −0.146 [−0.190, −0.099] | below 0 | 25% / 8% | 0/10 |

### Error mix (share of tasks)

| pack | model | invalid or no submit | overfill | sell before charge | end short | all idle | rate | cycle cap |
|---|---|---|---|---|---|---|---|---|
| 1. Foresight, eval-2025 | trained 4B, sampled | 0.5% | 6.0% | 2.5% | 2.5% | 0.0% | 0.5% | 1.0% |
| 1. Foresight, eval-2025 | GPT-6 Luna, effort high | 3.5% | 0.0% | 0.5% | 0.0% | 0.0% | 0.0% | 0.0% |
| 1. Foresight, eval-2025 | GPT-6 Luna, effort low | 0.5% | 7.5% | 5.0% | 2.5% | 0.5% | 0.0% | 0.5% |
| 1. Foresight, eval-2025 | GPT-6.1 Sol, effort high | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| 2. Foresight, fresh 10-18..27 | trained 4B, sampled | 0.5% | 6.1% | 1.9% | 1.4% | 0.0% | 0.3% | 0.8% |
| 2. Foresight, fresh 10-18..27 | GPT-6 Luna, effort high | 0.5% | 0.3% | 0.3% | 0.3% | 0.0% | 0.0% | 0.3% |
| 2. Foresight, fresh 10-18..27 | GPT-6 Luna, effort low | 0.5% | 6.3% | 4.1% | 2.2% | 0.3% | 0.3% | 1.4% |
| 2. Foresight, fresh 10-18..27 | GPT-6.1 Sol, effort high | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| 3a. Blind, eval-2025 | trained 4B, sampled | 0.0% | 2.3% | 5.7% | 1.7% | 0.0% | 1.3% | 0.7% |
| 3a. Blind, eval-2025 | GPT-6 Luna, effort high | 1.0% | 0.7% | 0.3% | 0.3% | 0.0% | 0.0% | 0.0% |
| 3a. Blind, eval-2025 | GPT-6 Luna, effort low | 0.3% | 11.7% | 2.0% | 1.7% | 0.0% | 0.7% | 0.3% |
| 3a. Blind, eval-2025 | GPT-6.1 Sol, effort high | 1.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| 3b. Blind, fresh 10-18..27 | trained 4B, sampled | 0.0% | 0.9% | 3.6% | 1.8% | 0.0% | 0.3% | 3.3% |
| 3b. Blind, fresh 10-18..27 | GPT-6 Luna, effort high | 1.2% | 0.3% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| 3b. Blind, fresh 10-18..27 | GPT-6 Luna, effort low | 1.8% | 12.1% | 0.9% | 2.7% | 0.0% | 0.6% | 0.9% |
| 3b. Blind, fresh 10-18..27 | GPT-6.1 Sol, effort high | 0.9% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
