"""
Headless Chart Generator:
Renders professional, clean multi-timeframe annotated chart images using matplotlib / mplfinance:
- Candlesticks
- EMA 20, 50, 200
- Bollinger Bands
- Dynamic Support / Resistance zones & key round levels
- Entry, Stop Loss, and TP1 / TP2 / TP3 target levels
- Completely headless (works smoothly in GitHub Actions and local servers)
"""
import os
import matplotlib
matplotlib.use("Agg")  # Headless backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
from typing import Dict, Any, Optional

ARTIFACTS_DIR = os.path.join(os.path.dirname(__file__), "..", "artifacts")
os.makedirs(ARTIFACTS_DIR, exist_ok=True)


class ChartGenerator:
    def __init__(self, output_dir: Optional[str] = None):
        self.output_dir = output_dir or ARTIFACTS_DIR
        os.makedirs(self.output_dir, exist_ok=True)

    def render_signal_chart(
        self,
        df: pd.DataFrame,
        symbol: str,
        timeframe: str,
        signal_data: Optional[Dict[str, Any]] = None,
        bars_to_show: int = 60
    ) -> str:
        """
        Renders a chart image and saves it to output_dir. Returns absolute file path.
        """
        plot_df = df.tail(bars_to_show).copy()
        fig, (ax_main, ax_rsi) = plt.subplots(
            2, 1, figsize=(12, 7), gridspec_kw={'height_ratios': [3.5, 1]}, sharex=True
        )
        fig.patch.set_facecolor('#131722')
        ax_main.set_facecolor('#131722')
        ax_rsi.set_facecolor('#131722')

        # Draw Candlesticks
        indices = range(len(plot_df))
        up = plot_df[plot_df['close'] >= plot_df['open']]
        down = plot_df[plot_df['close'] < plot_df['open']]

        col_up = '#089981'
        col_down = '#f23645'

        # Wicks
        ax_main.vlines(range(len(plot_df)), plot_df['low'], plot_df['high'], color='#787b86', linewidth=1)
        # Bodies
        ax_main.vlines(up.index.map(lambda x: plot_df.index.get_loc(x)), up['open'], up['close'], color=col_up, linewidth=4)
        ax_main.vlines(down.index.map(lambda x: plot_df.index.get_loc(x)), down['open'], down['close'], color=col_down, linewidth=4)

        # EMAs
        if 'ema_20' in plot_df.columns:
            ax_main.plot(indices, plot_df['ema_20'], color='#2962ff', label='EMA 20', linewidth=1.2)
        if 'ema_50' in plot_df.columns:
            ax_main.plot(indices, plot_df['ema_50'], color='#ff9800', label='EMA 50', linewidth=1.2)
        if 'ema_200' in plot_df.columns:
            ax_main.plot(indices, plot_df['ema_200'], color='#e91e63', label='EMA 200', linewidth=1.5)

        # Bollinger Bands
        if 'bb_upper' in plot_df.columns and 'bb_lower' in plot_df.columns:
            ax_main.plot(indices, plot_df['bb_upper'], color='#787b86', linestyle='--', linewidth=0.8, alpha=0.6)
            ax_main.plot(indices, plot_df['bb_lower'], color='#787b86', linestyle='--', linewidth=0.8, alpha=0.6)
            ax_main.fill_between(indices, plot_df['bb_upper'], plot_df['bb_lower'], color='#787b86', alpha=0.05)

        # Plot trade levels if available
        if signal_data and 'entry' in signal_data:
            entry = signal_data['entry']
            sl = signal_data['stop_loss']
            tp1 = signal_data['tp1']
            tp2 = signal_data['tp2']
            tp3 = signal_data.get('tp3')

            ax_main.axhline(entry, color='#2196f3', linestyle='-', linewidth=1.5, label=f'Entry: {entry}')
            ax_main.axhline(sl, color='#f23645', linestyle='--', linewidth=1.5, label=f'Stop Loss: {sl}')
            ax_main.axhline(tp1, color='#4caf50', linestyle=':', linewidth=1.2, label=f'TP1: {tp1}')
            ax_main.axhline(tp2, color='#089981', linestyle='--', linewidth=1.5, label=f'TP2: {tp2}')
            if tp3:
                ax_main.axhline(tp3, color='#00e676', linestyle='-.', linewidth=1.2, label=f'TP3: {tp3}')

        data_source = signal_data.get("data_source", "Yahoo Finance GC=F [Reference Futures]") if signal_data else "Market Data Feed"
        ax_main.grid(True, color='#2a2e39', linestyle='--', alpha=0.5)
        ax_main.tick_params(colors='#d1d4dc')
        ax_main.set_title(
            f"{symbol} ({timeframe}) — Gold Signal Pro Technical Analysis\n[Source: {data_source}] (Demo Forward Testing)",
            color='#ffffff', fontsize=12, fontweight='bold', pad=12
        )
        ax_main.legend(loc='upper left', facecolor='#1e222d', edgecolor='#2a2e39', labelcolor='#d1d4dc', fontsize=8)

        # RSI Panel
        if 'rsi_14' in plot_df.columns:
            ax_rsi.plot(indices, plot_df['rsi_14'], color='#ab47bc', linewidth=1.2)
            ax_rsi.axhline(70, color='#f23645', linestyle='--', linewidth=0.8, alpha=0.7)
            ax_rsi.axhline(30, color='#089981', linestyle='--', linewidth=0.8, alpha=0.7)
            ax_rsi.axhline(50, color='#787b86', linestyle=':', linewidth=0.6, alpha=0.5)
            ax_rsi.fill_between(indices, 30, 70, color='#ab47bc', alpha=0.08)
            ax_rsi.set_ylim(10, 90)
            ax_rsi.set_ylabel("RSI (14)", color='#d1d4dc', fontsize=9)
            ax_rsi.tick_params(colors='#d1d4dc')
            ax_rsi.grid(True, color='#2a2e39', linestyle='--', alpha=0.5)

        # Time labels formatting
        step = max(1, len(plot_df) // 6)
        tick_locs = list(range(0, len(plot_df), step))
        tick_labels = [plot_df.index[i].strftime('%d-%b %H:%M') for i in tick_locs]
        ax_rsi.set_xticks(tick_locs)
        ax_rsi.set_xticklabels(tick_labels, rotation=20, ha='right', color='#d1d4dc', fontsize=8)

        plt.tight_layout()
        file_name = f"{symbol}_{timeframe}_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.png"
        file_path = os.path.abspath(os.path.join(self.output_dir, file_name))
        fig.savefig(file_path, facecolor=fig.get_facecolor(), dpi=140, bbox_inches='tight')
        plt.close(fig)

        return file_path
