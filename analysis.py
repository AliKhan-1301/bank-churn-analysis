"""Bank customer churn analysis.

Usage: python analysis.py path/to/Churn_Modelling.csv

Reads the public "Churn Modelling" dataset (10,000 bank customers), runs the
statistical tests described in the README, and writes charts to figures/ and
the test results to results.json.
"""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

HERE = Path(__file__).resolve().parent
FIG = HERE / "figures"
FIG.mkdir(exist_ok=True)
BLUE, NAVY = "#1f8fff", "#12239e"

df = pd.read_csv(sys.argv[1])
res = {"customers": int(len(df)), "churned": int(df.Exited.sum()),
       "churn_rate": round(df.Exited.mean() * 100, 2)}

# 1. Churn rate by category, with chi-square tests of independence
df["AgeBand"] = pd.cut(df.Age, [17, 30, 40, 50, 60, 100],
                       labels=["18-30", "31-40", "41-50", "51-60", "61+"])
res["by_category"] = {}
for col in ["Geography", "Gender", "IsActiveMember", "HasCrCard", "NumOfProducts", "AgeBand"]:
    table = pd.crosstab(df[col], df.Exited)
    chi2, p, dof, _ = stats.chi2_contingency(table)
    n = table.to_numpy().sum()
    cramers_v = (chi2 / (n * (min(table.shape) - 1))) ** 0.5
    rates = (df.groupby(col, observed=True).Exited.mean() * 100).round(1)
    res["by_category"][col] = {
        "churn_rate_pct": {str(k): float(v) for k, v in rates.items()},
        "customers": {str(k): int(v) for k, v in df[col].value_counts().sort_index().items()},
        "chi2": round(chi2, 1), "dof": int(dof), "p": float(f"{p:.3g}"),
        "cramers_v": round(cramers_v, 3)}

# 2. Numeric variables: Welch t-test, churned vs retained
res["numeric"] = {}
for col in ["Age", "Balance", "CreditScore", "EstimatedSalary", "Tenure"]:
    a, b = df.loc[df.Exited == 1, col], df.loc[df.Exited == 0, col]
    t, p = stats.ttest_ind(a, b, equal_var=False)
    pooled = ((a.var() * (len(a) - 1) + b.var() * (len(b) - 1)) / (len(df) - 2)) ** 0.5
    res["numeric"][col] = {"mean_churned": round(a.mean(), 2), "mean_retained": round(b.mean(), 2),
                           "t": round(t, 2), "p": float(f"{p:.3g}"),
                           "cohens_d": round((a.mean() - b.mean()) / pooled, 3)}

# 3. One-way ANOVA: does average age or balance differ across countries?
res["anova"] = {}
for col in ["Age", "Balance"]:
    f, p = stats.f_oneway(*[g[col] for _, g in df.groupby("Geography")])
    res["anova"][col] = {"F": round(f, 2), "p": float(f"{p:.3g}"),
                         "means": {k: round(v, 2) for k, v in df.groupby("Geography")[col].mean().items()}}

# 4. Logistic regression on standardised numeric inputs, so coefficients compare
X = df[["CreditScore", "Age", "Tenure", "Balance", "NumOfProducts", "EstimatedSalary"]]
X = (X - X.mean()) / X.std()
X["Female"] = (df.Gender == "Female").astype(int)
X["Germany"] = (df.Geography == "Germany").astype(int)
X["Spain"] = (df.Geography == "Spain").astype(int)
X["IsActiveMember"] = df.IsActiveMember
X["HasCrCard"] = df.HasCrCard
model = sm.Logit(df.Exited, sm.add_constant(X)).fit(disp=0)
res["logit"] = {"pseudo_r2": round(model.prsquared, 3),
                "terms": {k: {"odds_ratio": round(float(np.exp(model.params[k])), 2),
                              "z": round(float(model.tvalues[k]), 2),
                              "p": float(f"{model.pvalues[k]:.3g}")}
                          for k in X.columns}}

(HERE / "results.json").write_text(json.dumps(res, indent=2))

# Charts
def bar(col, title, fname, order=None):
    r = df.groupby(col, observed=True).Exited.mean() * 100
    if order:
        r = r.loc[order]
    fig, ax = plt.subplots(figsize=(6, 3.6))
    bars = ax.bar([str(i) for i in r.index], r.values, color=BLUE)
    ax.axhline(df.Exited.mean() * 100, color=NAVY, ls="--", lw=1,
               label=f"Overall {df.Exited.mean() * 100:.1f}%")
    ax.legend(loc="upper left", frameon=False, fontsize=9)
    for b in bars:
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.6, f"{b.get_height():.1f}%", ha="center", fontsize=9)
    ax.set_ylabel("Churn rate (%)"); ax.set_title(title)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(FIG / fname, dpi=150); plt.close(fig)

bar("Geography", "Churn rate by country", "churn-by-country.png")
bar("AgeBand", "Churn rate by age band", "churn-by-age.png")
bar("NumOfProducts", "Churn rate by number of products held", "churn-by-products.png")
df["Activity"] = df.IsActiveMember.map({1: "Active member", 0: "Inactive member"})
bar("Activity", "Churn rate by activity", "churn-by-activity.png")

terms = pd.Series({k: v["z"] for k, v in res["logit"]["terms"].items()}).sort_values()
fig, ax = plt.subplots(figsize=(6, 3.8))
ax.barh(terms.index, terms.values, color=[NAVY if v > 0 else BLUE for v in terms.values])
ax.axvline(0, color="black", lw=0.8)
ax.set_xlabel("z-statistic (right: raises churn odds, left: lowers them)")
ax.set_title("Logistic regression: strength of each driver")
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout(); fig.savefig(FIG / "logit-drivers.png", dpi=150); plt.close(fig)
print(json.dumps(res, indent=1))
