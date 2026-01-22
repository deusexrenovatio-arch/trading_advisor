from __future__ import annotations

from dash import dash_table, html


def signals_layout(df):
    return html.Div(
        [
            html.H3("Signals"),
            dash_table.DataTable(
                data=df.to_dict("records"),
                columns=[{"name": col, "id": col} for col in df.columns],
                page_size=15,
                style_table={"overflowX": "auto"},
            ),
        ]
    )
