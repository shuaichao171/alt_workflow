"""图集打包（shelf 装箱）。

DST Mod Tool 的 dst-core/src/image/atlas.rs 内部策略未在静态分析中恢复（idalib 后端
对该 70MB 二进制不可用）；此处提供等效 shelf 打包器（面积降序 + 行填充 + pow2 画布），
满足 DST 图集的 pow2/边距约束。
"""


class ShelfPacker:
    """shelf 打包：按面积降序放置，行内从左到右，超出宽度换行，画布取 pow2。"""

    def __init__(self, max_width=2048, max_height=2048, padding=0):
        self.max_width, self.max_height, self.padding = max_width, max_height, padding
        self.rows = []   # [(y, height, [(name, x, w)])]

    def pack(self, items):
        """items: [(name, w, h)] -> (dict name->(x,y), (canvas_w, canvas_h))"""
        placed = {}
        for name, w, h in sorted(items, key=lambda t: (-(t[1] * t[2]), t[1])):
            w2, h2 = w + self.padding, h + self.padding
            pos = self._place(name, w2, h2)
            if pos is None:
                raise ValueError(f'cannot place {name} ({w}x{h}) in '
                                 f'{self.max_width}x{self.max_height}')
            placed[name] = pos
        return placed, self.size()

    def _place(self, name, w, h):
        for row in self.rows:
            if row[1] >= h:
                last = row[2][-1]
                x = last[2] + (last[1] - last[1])  # x after last item
                x = row[2][-1][2]
                if x + w <= self.max_width:
                    row[2].append((name, x, x + w))
                    return (x, row[0])
        y = sum(r[1] for r in self.rows)
        if y + h <= self.max_height and w <= self.max_width:
            self.rows.append((y, h, [(name, 0, w)]))
            return (0, y)
        return None

    def size(self):
        h = sum(r[1] for r in self.rows)
        w = max((r[2][-1][2] for r in self.rows), default=0)
        return _pow2(w), _pow2(h)


def _pow2(v):
    p = 1
    while p < v:
        p <<= 1
    return p
