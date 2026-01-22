from __future__ import annotations

from typing import Iterable

from moex_carry.domain.models import ContractSpec, Instrument, PairMapping


def build_pair_mappings(
    stocks: Iterable[Instrument], futures: Iterable[ContractSpec]
) -> list[PairMapping]:
    stock_map = {instrument.secid: instrument for instrument in stocks}
    mappings: list[PairMapping] = []
    for future in futures:
        if future.asset_code in stock_map:
            mappings.append(
                PairMapping(
                    stock_secid=future.asset_code,
                    future_secid=future.secid,
                    expiry=future.expiry,
                )
            )
    return mappings
