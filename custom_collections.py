from typing import List, Optional
from playwright.async_api import Page


class PageNode:
    def __init__(self, page: Page, url: str):
        self.page      = page
        self.url       = url
        self.page_data: Optional[List[dict]] = None
        self.next:      Optional['PageNode'] = None
        self.prev:      Optional['PageNode'] = None


class PageList:
    def __init__(self):
        self.head:    Optional[PageNode] = None
        self.current: Optional[PageNode] = None

    def add_page(self, page: Page):
        node = PageNode(page=page, url=page.url)
        if not self.head:
            # first page
            self.head    = node
            self.current = node
            return
        # link new node at end
        node.prev        = self.current
        self.current.next = node
        self.current     = node

    def current_page(self) -> Optional[Page]:
        return self.current.page if self.current else None

    def go_back(self):
        if self.current and self.current.prev:
            self.current = self.current.prev

    def go_next(self):
        if self.current and self.current.next:
            self.current = self.current.next
        else:
            print("No next page.")


class PlanQueue:
    def __init__(self):
        self._queue: List[dict] = []

    def is_empty(self) -> bool:
        return len(self._queue) == 0

    def add(self, step: dict):
        self._queue.append(step)

    def add_steps(self, steps: List[dict]):
        self._queue.extend(steps)

    def pop(self) -> Optional[dict]:
        if self.is_empty():
            return None
        return self._queue.pop(0)

    def clear(self):
        self._queue.clear()

    def __len__(self):
        return len(self._queue)