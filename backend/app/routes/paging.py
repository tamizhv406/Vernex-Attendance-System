"""How far a list may be paged: one rule for every route that answers a page at a time.

A page number comes from the address, so it can be anything. Without an upper limit a large one
becomes an offset the database cannot hold, and the request fails with a server error instead of
being refused. Here it is refused (422) before the database is asked.
"""
from typing import Annotated

from fastapi import Query

# Rows on one page.
MAX_PAGE_SIZE = 100
# 10,000 pages of at most 100 rows: an offset of at most 999,900, beyond any list this system holds
# and far inside every database's integer range.
MAX_PAGE = 10_000

PageNumber = Annotated[int, Query(ge=1, le=MAX_PAGE)]
PageSize = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)]
