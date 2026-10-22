---
title: Calculate derived columns
summary: Create numeric, grouped and ordered measurements without changing the source table.
status: partial
---

**Calculate** creates columns from the values already loaded in a table or run workspace. Calculations
update with edits and use all loaded rows, including rows hidden by a filter. They are view definitions;
saving a workflow preserves the calculation rather than writing it into the original dataset.

## Create a calculation

1. Open the table or run and choose **Calculate**.
2. Enter a unique column name, choose the operation, then select the required inputs.
3. For grouped operations, choose the grouping columns. Include source identity when sample IDs
   can repeat between datasets.
4. For ordered operations, choose a numeric order column such as `epoch`.
5. Add the calculation and inspect known examples before filtering or charting the result.

For image aspect ratio, divide width by height. For a per-image change across epochs, choose
**Change from previous**, group by sample identity and source, and order by epoch. Grouping only by
class would instead compare different samples within that class.

## Included operations

| Family | Operations |
|---|---|
| Arithmetic | Add, subtract, multiply, divide, power, absolute value, negate, square root, log, round, floor, ceiling |
| Row summaries | Sum, mean, minimum, maximum |
| Vectors and strings | Euclidean vector length, text length, vector distance, dot product |
| Comparison | Equality, greater than, less than |
| Across rows | Ascending rank with average ties, occurrence count |
| Within groups | Sum, mean, minimum, maximum, row count, population standard deviation, standardisation |
| Ordered observations | Previous, next, change from previous, cumulative sum |

Numeric inputs must be finite. Division by zero and invalid numeric domains produce missing values.
Previous/next has no neighbour at the corresponding endpoint. Group count counts rows, while numeric
summaries ignore missing numeric inputs. Standardisation returns zero for a constant numeric group.

## Reuse and boundaries

Later calculations may use earlier calculated columns. Removing a required input can make dependent
analysis invalid; fix the dependency before reapplying a workflow. The current limit is 64 calculated
columns, with up to 16 input/group references per definition.

There is no claim of a complete general-purpose expression language. Additional array, text, time,
geometry, neighbour and foreign-table operators are **Not yet included** in this menu; see the
[reserved operator groups](/docs/planned/advanced-analysis#additional-calculation-operators).
