# ADR 0004: Erase table borders before OCR

**Status:** accepted (stage 6)

## Context
On scanned invoices tesseract (`rus+eng`, `--psm 6`) read the header and totals but turned table rows into noise:
the borders of the cells break line segmentation.

## Measurement (scan of invoice 002, 8 table values: names, prices, amounts)
| Config | Values recovered | Time |
|---|---|---|
| `--psm 6` | 0 / 8 | 6.2 s |
| `--psm 4` | 0 / 8 | 5.8 s |
| `--psm 3` | 0 / 8 | 6.4 s |
| borders removed + `--psm 6` | **8 / 8** | 5.3 s |
| borders removed + `--psm 4` | 6 / 8 | 5.9 s |

## Decision
`app/text.py:remove_rules` erases dark horizontal runs longer than ~4 % of the page width and vertical runs
longer than ~1.7 % of its height, then OCR runs with `--psm 6`. Text strokes are much shorter and survive.

## Effect on the whole dataset (`rules` provider, 16 scans of 56 documents)
Field accuracy on scans 57 % → 84 %; overall 61 % → 83 % (together with a fixed act-title rule).
