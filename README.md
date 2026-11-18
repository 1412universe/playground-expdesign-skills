# Playground experimental-design skills

Public copies of four Skills submitted to Bohrium Playground, contest `bohr-product`, period 4, track Experimental Design. Each directory is the Skill installed at `/skills/weekly-skill` for that challenge. The `examples/` folders are synthetic interface demos, not the organizer's official cases.

| Challenge | Directory |
|---|---|
| [实验方案可行性评估](https://play.bohrium.com/challenge/challenge-2e2c5820) | [feasibility](feasibility) |
| [实验参数优化建议](https://play.bohrium.com/challenge/challenge-ec02b694) | [parameter-optimization](parameter-optimization) |
| [实验方案比较与选择](https://play.bohrium.com/challenge/challenge-7be76e91) | [plan-comparison](plan-comparison) |
| [实验结果解释与异常分析](https://play.bohrium.com/challenge/challenge-8354c69a) | [result-interpretation](result-interpretation) |

Run one Skill locally:

```bash
python3 feasibility/scripts/run_case.py --selftest
python3 feasibility/scripts/run_case.py --input feasibility/examples/input --output /tmp/ed-out --work /tmp/ed-work
```
