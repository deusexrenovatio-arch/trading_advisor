from __future__ import annotations

from typing import Iterable

from moex_carry.domain.models import ContractSpec, Instrument, PairMapping

# Some futures use asset codes that differ from the underlying stock SECID.
ASSET_CODE_ALIASES = {
    "SBRF": "SBER",
    "GAZR": "GAZP",
}


def build_pair_mappings(
    stocks: Iterable[Instrument], futures: Iterable[ContractSpec]
) -> list[PairMapping]:
    stock_map = {instrument.secid: instrument for instrument in stocks}
    mappings: list[PairMapping] = []
    for future in futures:
        asset_code = ASSET_CODE_ALIASES.get(future.asset_code, future.asset_code)
        if asset_code in stock_map:
            mappings.append(
                PairMapping(
                    stock_secid=asset_code,
                    future_secid=future.secid,
                    expiry=future.expiry,
                )
            )
    return mappings
