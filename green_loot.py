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


@dataclass(frozen=True)
class LootObservation:
    status: str  # found, absent_visible, uncertain
    target_score: float
    panel_header_score: float
    panel_label_score: float
    target_box: tuple[int, int, int, int] | None
    reason: str


def _read(path: Path) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f'无法读取图片: {path}')
    return image


def _best_match(image: np.ndarray, template: np.ndarray, region: tuple[int, int, int, int], scales: tuple[float, ...]):
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
        if score > best[0]:
            best = (float(score), (x + x1, y + y1, w, h))
    return best


def inspect(image: np.ndarray) -> LootObservation:
    if image is None or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError('需要 BGR 彩色截图')
    height, width = image.shape[:2]
    if 1919 <= width <= 1930 and 1079 <= height <= 1130:
        # The game window may extend below the desktop; the supplied reference
        # screenshots show only its top-left 1919×1079 visible region.
        image = image[:1079, :1919]
        height, width = image.shape[:2]
    expected_ratio = BASE_SIZE[0] / BASE_SIZE[1]
    if abs(width / height - expected_ratio) > 0.035:
        return LootObservation('uncertain', 0, 0, 0, None, '窗口比例与校准截图不同')
    frame = cv2.resize(image, BASE_SIZE, interpolation=cv2.INTER_AREA)
    header = _read(ASSET_DIR / 'panel_header.png')
    label = _read(ASSET_DIR / 'panel_label.png')
    target = _read(ASSET_DIR / 'green_coat.png')
    header_score, _ = _best_match(frame, header, PANEL_REGION, (1.0,))
    label_score, _ = _best_match(frame, label, PANEL_REGION, (1.0,))
    if header_score < PANEL_SCORE or label_score < PANEL_SCORE:
        return LootObservation('uncertain', 0, round(header_score, 3),
                               round(label_score, 3), None, '未确认战利品面板完整打开')
    scales = (.65, .7, .75, .8, .85, .9, .95, 1.0, 1.05, 1.1, 1.15, 1.2)
    target_score, box = max(
        (_best_match(frame, target, region, scales) for region in _loot_regions()),
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
                           round(label_score, 3), box, reason)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='只读检查战斗中已打开的战利品面板')
    parser.add_argument('screenshot', type=Path)
    args = parser.parse_args()
    print(json.dumps(asdict(inspect(_read(args.screenshot))), ensure_ascii=False, indent=2))
