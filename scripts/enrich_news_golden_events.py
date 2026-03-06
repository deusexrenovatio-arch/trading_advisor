from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from moex_carry.news_causal import analyze_causal_news


def _norm_text(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass
    return " ".join(str(value).strip().split())


def _norm_bool(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _fallback_event(commodity: str, text: str) -> tuple[str, str]:
    lowered = _norm_text(text).lower()
    commodity_key = _norm_text(commodity).upper()

    if commodity_key == "COCOA":
        if any(token in lowered for token in ("farmgate", "cocobod", "unpaid", "harmattan", "crop disease", "ghana")):
            return "cocoa_crop_shock", "cause"
        if any(token in lowered for token in ("mid crop", "arrivals", "surplus", "stocks", "crop development")):
            return "cocoa_supply_recovery", "cause"
    if commodity_key == "NICKEL":
        if any(token in lowered for token in ("quota", "permit", "slashed", "production limits", "ore ban", "morowali")):
            return "nickel_ore_export_restriction", "cause"
        if any(token in lowered for token in ("output increase", "higher production", "project ramp", "oversupply")):
            return "nickel_supply_surge", "cause"
    if commodity_key == "COFFEE":
        if any(token in lowered for token in ("frost", "drought", "flowering stress")):
            return "coffee_crop_weather_shock", "cause"
        if any(
            token in lowered
            for token in (
                "record coffee harvest",
                "conab",
                "crop prospects",
                "brazil rains",
                "harvest more beans",
                "arabica prices fall",
            )
        ):
            return "coffee_supply_recovery", "cause"
    if commodity_key == "COPPER":
        if any(token in lowered for token in ("strike", "disrupt access", "escondida", "lower level", "sacks executives")):
            return "copper_mine_disruption", "cause"
        if any(token in lowered for token in ("lift copper output", "mine extension", "environmental permit", "investments")):
            return "copper_supply_recovery", "cause"
    if commodity_key == "ALUMINUM":
        if any(
            token in lowered
            for token in ("shutdown", "force majeure", "natural gas shortage", "smelter", "alumina duty", "bauxite disruption")
        ):
            return "smelter_power_disruption", "cause"
        if any(token in lowered for token in ("exports jump", "output increase", "smelter restart")):
            return "smelter_restart", "cause"

    if any(token in lowered for token in ("export ban", "export quota", "sanction", "embargo")):
        return "export_restriction", "cause"
    if any(token in lowered for token in ("outage", "shutdown", "force majeure", "attack", "strike")):
        return "producer_outage", "mixed"
    return "", "unknown"


_EVENT_ROUTE_FALLBACK: dict[str, str] = {
    "cocoa_crop_shock": "producer:ghana->flow:cocoa_export_supply->COCOA",
    "cocoa_supply_recovery": "producer:ivory_coast->flow:cocoa_export_supply->COCOA",
    "nickel_ore_export_restriction": "producer:indonesia->flow:nickel_ore_supply->NICKEL",
    "nickel_supply_surge": "producer:indonesia->flow:nickel_ore_supply->NICKEL",
    "coffee_crop_weather_shock": "producer:brazil->flow:coffee_export_supply->COFFEE",
    "coffee_supply_recovery": "producer:brazil->flow:coffee_export_supply->COFFEE",
    "copper_mine_disruption": "producer:chile->flow:copper_mine_supply->COPPER",
    "copper_supply_recovery": "producer:chile->flow:copper_mine_supply->COPPER",
    "smelter_power_disruption": "producer:qatar->flow:aluminum_smelter_supply->ALUMINUM",
    "smelter_restart": "producer:china->flow:aluminum_smelter_supply->ALUMINUM",
    "producer_outage": "producer->flow:supply->commodity",
    "export_restriction": "regulator->flow:supply->commodity",
}

_DEFAULT_EVENT_BY_COMMODITY: dict[str, str] = {
    "BRN": "middle_east_supply_risk",
    "NG_US": "extreme_weather_supply_shock",
    "GOLD": "risk_off_geopolitics",
    "SILVER": "manufacturing_upturn",
    "PLATINUM": "pgm_mine_disruption",
    "PALLADIUM": "russian_palladium_supply_risk",
    "COPPER": "copper_mine_disruption",
    "ALUMINUM": "smelter_power_disruption",
    "NICKEL": "nickel_ore_export_restriction",
    "ZINC": "zinc_smelter_disruption",
    "WHEAT": "grain_export_restriction",
    "SUGAR": "sugar_export_restriction",
    "COFFEE": "coffee_supply_recovery",
    "COCOA": "cocoa_crop_shock",
    "ORANGE": "citrus_crop_shock",
}

_DEFAULT_ROUTE_BY_COMMODITY: dict[str, str] = {
    "BRN": "exporter:iran->seaborne_crude->BRN",
    "NG_US": "exporter:qatar->lng_shipping->NG_US",
    "GOLD": "macro:rates_fx->safe_haven->GOLD",
    "SILVER": "industrial:solar->demand->SILVER",
    "PLATINUM": "producer:south_africa->pgm_supply->PLATINUM",
    "PALLADIUM": "producer:russia->palladium_supply->PALLADIUM",
    "COPPER": "producer:chile->copper_mine_supply->COPPER",
    "ALUMINUM": "producer:china->aluminum_smelter_supply->ALUMINUM",
    "NICKEL": "producer:indonesia->nickel_ore_supply->NICKEL",
    "ZINC": "producer:china->zinc_mine_supply->ZINC",
    "WHEAT": "producer:russia->wheat_export_supply->WHEAT",
    "SUGAR": "producer:india->sugar_export_supply->SUGAR",
    "COFFEE": "producer:brazil->coffee_export_supply->COFFEE",
    "COCOA": "producer:ghana->cocoa_export_supply->COCOA",
    "ORANGE": "producer:brazil->orange_juice_supply->ORANGE",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich GOLD known-events dataset with cause_event and cause_route_key.")
    parser.add_argument("--input-csv", type=Path, default=Path("docs/research/news_golden_events_gold.csv"))
    parser.add_argument("--output-csv", type=Path, default=None)
    parser.add_argument("--only-root", action="store_true", default=True)
    args = parser.parse_args()

    if not args.input_csv.exists():
        raise SystemExit(f"Input file not found: {args.input_csv}")
    output_csv = args.output_csv or args.input_csv

    df = pd.read_csv(args.input_csv)
    if "root_hit" not in df.columns:
        raise SystemExit("Expected `root_hit` column in GOLD dataset.")
    if "commodity" not in df.columns or "title" not in df.columns:
        raise SystemExit("Expected `commodity` and `title` columns in GOLD dataset.")

    root_mask = df["root_hit"].map(_norm_bool)
    edit_mask = root_mask.copy() if args.only_root else pd.Series(True, index=df.index)

    updated_event = 0
    updated_route = 0
    updated_class = 0

    for idx, row in df[edit_mask].iterrows():
        commodity = _norm_text(row.get("commodity")).upper()
        title = _norm_text(row.get("title"))
        description = _norm_text(row.get("description"))
        content = _norm_text(row.get("content"))
        manual_note = _norm_text(row.get("manual_note"))
        text_blob = " ".join(part for part in (title, description, content, manual_note) if part)

        payload = analyze_causal_news(
            commodity=commodity,
            title=title,
            description=description,
            content=f"{content} {manual_note}".strip(),
            direction="hold",
        )
        payload_event = _norm_text(payload.get("cause_event")).lower()
        payload_route = _norm_text(payload.get("cause_route_key"))
        payload_class = _norm_text(payload.get("cause_classification")).lower()
        payload_claim = _norm_text(payload.get("cause_claim_status")).lower() or "confirmed"

        current_event = _norm_text(row.get("cause_event")).lower()
        current_route = _norm_text(row.get("cause_route_key"))
        current_class = _norm_text(row.get("cause_classification")).lower()

        fallback_event, fallback_class = _fallback_event(commodity, text_blob)
        if not fallback_event:
            fallback_event = _DEFAULT_EVENT_BY_COMMODITY.get(commodity, "")
            if fallback_event:
                fallback_class = "mixed"
        chosen_event = current_event or payload_event or fallback_event
        chosen_class = current_class or payload_class or fallback_class or "unknown"
        chosen_route = (
            current_route
            or payload_route
            or _EVENT_ROUTE_FALLBACK.get(chosen_event, "")
            or _DEFAULT_ROUTE_BY_COMMODITY.get(commodity, "")
        )

        if chosen_event and current_event != chosen_event:
            df.at[idx, "cause_event"] = chosen_event
            updated_event += 1
        if chosen_route and current_route != chosen_route:
            df.at[idx, "cause_route_key"] = chosen_route
            updated_route += 1
        if chosen_class and current_class != chosen_class:
            df.at[idx, "cause_classification"] = chosen_class
            updated_class += 1
        if not _norm_text(row.get("cause_claim_status")):
            df.at[idx, "cause_claim_status"] = payload_claim or "confirmed"
        if pd.isna(row.get("is_primary_cause")):
            df.at[idx, "is_primary_cause"] = True

    df.to_csv(output_csv, index=False)

    root_rows = int(root_mask.sum())
    root_with_event = int(df[root_mask]["cause_event"].map(lambda value: bool(_norm_text(value))).sum())
    root_with_route = int(df[root_mask]["cause_route_key"].map(lambda value: bool(_norm_text(value))).sum())
    print("GOLD enrichment completed")
    print(f"- output: {output_csv}")
    print(f"- root_rows: {root_rows}")
    print(f"- root_with_cause_event: {root_with_event}")
    print(f"- root_with_cause_route: {root_with_route}")
    print(f"- updated_event_rows: {updated_event}")
    print(f"- updated_route_rows: {updated_route}")
    print(f"- updated_class_rows: {updated_class}")


if __name__ == "__main__":
    main()
