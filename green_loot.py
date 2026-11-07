"""Read-only detector for the depth-10 green coat in the battle loot panel.

This module deliberately reports only what is visible *now*.  The caller must
verify that the intended enemy wave has finished before treating an absent
item as a reason to abandon a battle.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from app_paths import RESOURCE_ROOT, FROZEN

if not FROZEN and sys.prefix == sys.base_prefix and (RESOURCE_ROOT / '.runtime').exists():
    sys.path.insert(0, str(RESOURCE_ROOT / '.runtime'))

import cv2
import numpy as np

BASE_SIZE = (1919, 1079)  # screenshot including the Windows title bar
ASSET_DIR = RESOURCE_ROOT / 'assets' / 'green_loot'
TARGET_SCORE = 0.88
POSSIBLE_TARGET_SCORE = 0.65
PANEL_SCORE = 0.82
PANEL_REGION = (650, 54, 1260, 238)


def _loot_regions():
    """Eight columns, up to three visible rows in the calibrated panel."""
    for row_y in (245, 505, 765):
        for column in range(8):
            x = 137 + 202 * column
            yield (x, row_y, x + 183, row_y + 177)


def _loot_column_regions():
    """Full vertical column strips so scrolled rows at any Y offset are scanned."""
    for column in range(8):
        x = 137 + 202 * column
        yield (x, 230, x + 183, 1040)


def _detect_scrollbar(frame: np.ndarray) -> tuple[bool, bool, int | None, int | None]:
    """Detect the right-side scrollbar thumb (x=1754..1774, y=226..1050)."""
    strip = cv2.cvtColor(frame[226:1050, 1754:1774], cv2.COLOR_BGR2GRAY)
    row_max = strip.max(axis=1)
    bright = np.where(row_max > 150)[0]
    if len(bright) < 20:
        return False, False, None, None
    thumb_top = int(226 + bright[0])
    thumb_bottom = int(226 + bright[-1])
    return True, bool(thumb_bottom < 1020), thumb_top, thumb_bottom


@dataclass(frozen=True)
class LootObservation:
    status: str  # found, absent_visible, uncertain
    target_score: float
    panel_header_score: float
    panel_label_score: float
    target_box: tuple[int, int, int, int] | None
    reason: str
    has_scrollbar: bool = False
    can_scroll_down: bool = False
    thumb_top: int | None = None
    thumb_bottom: int | None = None


def _read(path: Path) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f'无法读取图片: {path}')
    return image


def _best_match(image: np.ndarray, template: np.ndarray, region: tuple[int, int, int, int],
                scales: tuple[float, ...], min_std: float = 0.0):
    x1, y1, x2, y2 = region
    area = image[y1:y2, x1:x2]
    best = (0.0, None)
    for scale in scales:
        scaled = cv2.resize(template, None, fx=scale, fy=scale,
                            interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_NEAREST)
        h, w = scaled.shape[:2]
        if h > area.shape[0] or w > area.shape[1]:
            continue
        result = cv2.matchTemplate(area, scaled, cv2.TM_CCOEFF_NORMED)
        _, score, _, (x, y) = cv2.minMaxLoc(result)
        if min_std > 0.0 and float(area[y:y + h, x:x + w].std()) < min_std:
            continue
        if score > best[0]:
            best = (float(score), (x + x1, y + y1, w, h))
    return best


def inspect(image: np.ndarray) -> LootObservation:
    if image is None or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError('需要 BGR 彩色截图')
    height, width = image.shape[:2]
    tb = 0
    if height >= 50 and width >= 400:
        mid = image[:45, int(width * 0.15):int(width * 0.80), :]
        row_std = mid.std(axis=(1, 2))
        row_diff = np.abs(np.diff(mid.mean(axis=(1, 2))))
        for y in range(20, min(42, height - 1)):
            if row_std[y] < 12.0 and (row_diff[y] > 8.0 or row_std[y + 1] > 15.0):
                tb = y + 1
                break
        if tb == 0:
            client_w = width - 2 if (width - 2) % 16 == 0 else width
            tb_geom = height - round(client_w * 9 / 16) - (1 if (width - 2) % 16 == 0 else 0)
            if 20 <= tb_geom <= 42:
                tb = tb_geom
    if tb > 0 and abs(width / max(1, height - tb) - (16.0 / 9.0)) <= 0.05 and height - tb >= 700:
        top_bar = cv2.resize(image[:tb, :], (BASE_SIZE[0], 38), interpolation=cv2.INTER_AREA)
        client_1080 = cv2.resize(image[tb:, :], (BASE_SIZE[0], 1080), interpolation=cv2.INTER_AREA)
        frame = np.vstack([top_bar, client_1080])[:BASE_SIZE[1], :BASE_SIZE[0]].copy()
    elif 1919 <= width <= 1930 and 1079 <= height <= 1130:
        # The game window may extend below the desktop; the supplied reference
        # screenshots show only its top-left 1919×1079 visible region.
        image = image[:1079, :1919]
        height, width = image.shape[:2]
        frame = cv2.resize(image, BASE_SIZE, interpolation=cv2.INTER_AREA)
    elif width >= 1000 and height >= 600:
        if abs(width / height - (BASE_SIZE[0] / BASE_SIZE[1])) > 0.05:
            return LootObservation('uncertain', 0, 0, 0, None, '窗口比例与校准截图不同')
        frame = cv2.resize(image, BASE_SIZE, interpolation=cv2.INTER_AREA)
    else:
        return LootObservation('uncertain', 0, 0, 0, None, '窗口比例与校准截图不同')
    header = _read(ASSET_DIR / 'panel_header.png')
    label = _read(ASSET_DIR / 'panel_label.png')
    target = _read(ASSET_DIR / 'green_coat.png')
    header_score, _ = _best_match(frame, header, PANEL_REGION, (0.95, 1.0, 1.05))
    label_score, _ = _best_match(frame, label, PANEL_REGION, (0.95, 1.0, 1.05))
    if header_score < PANEL_SCORE or label_score < PANEL_SCORE:
        return LootObservation('uncertain', 0, round(header_score, 3),
                               round(label_score, 3), None, '未确认战利品面板完整打开')
    has_scrollbar, can_scroll_down, thumb_top, thumb_bottom = _detect_scrollbar(frame)
    scales = (.65, .7, .75, .8, .85, .9, .95, 1.0, 1.05, 1.1, 1.15, 1.2)
    regions = list(_loot_regions())
    if has_scrollbar:
        regions.extend(_loot_column_regions())
    target_score, box = max(
        (_best_match(frame, target, region, scales, min_std=18.0) for region in regions),
        key=lambda result: result[0],
    )
    if target_score >= TARGET_SCORE:
        status = 'found'
    elif target_score >= POSSIBLE_TARGET_SCORE:
        status = 'uncertain'
    else:
        status = 'absent_visible'
    if box is not None:
        x, y, w, h = box
        box = (round(x * width / BASE_SIZE[0]), round(y * height / BASE_SIZE[1]),
               round(w * width / BASE_SIZE[0]), round(h * height / BASE_SIZE[1]))
    reason = {
        'found': '看到绿衣图标',
        'uncertain': '存在相似图标，需要人工确认',
        'absent_visible': '当前可见列表未看到绿衣；仍需确认检查时机和列表完整',
    }[status]
    return LootObservation(status, round(target_score, 3), round(header_score, 3),
                           round(label_score, 3), box, reason,
                           has_scrollbar, can_scroll_down, thumb_top, thumb_bottom)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='只读检查战斗中已打开的战利品面板')
    parser.add_argument('screenshot', type=Path)
    args = parser.parse_args()
    print(json.dumps(asdict(inspect(_read(args.screenshot))), ensure_ascii=False, indent=2))
