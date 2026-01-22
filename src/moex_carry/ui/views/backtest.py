from __future__ import annotations

from dash import dash_table, html


def backtest_layout(df):
    return html.Div(
        [
            html.H3("Backtest summary"),
            dash_table.DataTable(
                data=df.to_dict("records"),
                columns=[{"name": col, "id": col} for col in df.columns],
                page_size=10,
                style_table={"overflowX": "auto"},
            ),
        ]
    )
