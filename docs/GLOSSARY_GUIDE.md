# Glossary Guide

Use `backend/glossary.csv` to improve professional translation wording without editing Python code.

## How To Add Terms

1. Open `backend/glossary.csv`.
2. Add one row for each professional term.
3. Save the file as UTF-8 CSV.
4. Restart Subtitle Studio so the backend reloads the latest glossary.
5. Test with a short sentence that contains the English trigger term.

## Columns

- `source_term`: English term or abbreviation heard in the meeting.
- `target_term`: preferred Simplified Chinese translation.
- `wrong_outputs`: common wrong Chinese outputs to replace, separated by semicolons.
- `trigger_terms`: English words or phrases that activate the row, separated by semicolons.
- `domain`: optional subject area such as `pharma`, `HVAC`, `validation`, or `civil engineering`.
- `note`: optional reminder for when this wording should be used.

## Example Rows

```csv
source_term,target_term,wrong_outputs,trigger_terms,domain,note
commissioning,调试,委托;佣金,commissioning;commissioning plan,engineering,工程投运前调试语境
FAT,工厂验收测试,脂肪,FAT;factory acceptance test,project,
WFI,注射用水,注射水,WFI;water for injection,pharma,
```

## Practical Tips

- Put the wrong machine translation in `wrong_outputs`, not only the correct term.
- Add both abbreviation and full phrase in `trigger_terms`, for example `WFI;water for injection`.
- For ambiguous words, use narrower triggers. For example, use `industrial developer` for `开发商` instead of forcing every `developer`.
- Keep rows short and specific. It is safer to add several precise rows than one broad replacement.
