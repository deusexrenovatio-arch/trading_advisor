from __future__ import annotations

from dash import dash_table, html


def top_pairs_layout(df):
    return html.Div(
        [
            html.H3("Top pairs"),
            dash_table.DataTable(
                data=df.to_dict("records"),
                columns=[{"name": col, "id": col} for col in df.columns],
                page_size=15,
                style_table={"overflowX": "auto"},
            ),
        ]
    )
