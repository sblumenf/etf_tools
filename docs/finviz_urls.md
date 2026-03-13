# Finviz Screener URLs — Covered Call & Collar Candidates

## Base Filters (applied to all)
- Optionable
- Avg volume > 500K
- No dividend
- Market cap > $2B
- Sorted by volume descending

Base filter string: `f=sh_opt_option,sh_avgvol_o500,fa_div_none,cap_midover`
Sort: `o=-volume`

Note: Earnings 60+ days filter does not exist in Finviz. Scrape earnings date from `v=161` view and filter post-scrape.

---

## URLs

### 1. High Weekly Volatility (IV rank proxy)
https://finviz.com/screener.ashx?v=171&f=sh_opt_option,sh_avgvol_o500,fa_div_none,cap_midover,ta_volatility_wo5&o=-volume

### 2. Post-Earnings + Still Volatile
https://finviz.com/screener.ashx?v=171&s=ta_e_after&f=sh_opt_option,sh_avgvol_o500,fa_div_none,cap_midover,ta_volatility_wo5&o=-volume

### 3. High Short Interest (>15%)
https://finviz.com/screener.ashx?v=131&f=sh_opt_option,sh_avgvol_o500,fa_div_none,cap_midover,sh_short_o15&o=-volume

### 4. High Short Interest (>20%)
https://finviz.com/screener.ashx?v=131&f=sh_opt_option,sh_avgvol_o500,fa_div_none,cap_midover,sh_short_o20&o=-volume

### 5. Gap Up >5% + High Volatility
https://finviz.com/screener.ashx?v=171&f=sh_opt_option,sh_avgvol_o500,fa_div_none,cap_midover,ta_gap_u5,ta_volatility_wo3&o=-volume

### 6. Big Monthly Gain, Flat This Week (gap-up consolidation proxy)
https://finviz.com/screener.ashx?v=171&f=sh_opt_option,sh_avgvol_o500,fa_div_none,cap_midover,ta_perf_4w_o10,ta_perf_1w_d&o=-volume

### 7. 20%+ Above 200-Day SMA + Overbought RSI (collar candidates)
https://finviz.com/screener.ashx?v=171&f=sh_opt_option,sh_avgvol_o500,fa_div_none,cap_midover,ta_sma200_pa20,ta_rsi_ob70&o=-volume

### 8. Overbought Signal + 20%+ Above 200-Day SMA
https://finviz.com/screener.ashx?v=171&s=ta_overbought&f=sh_opt_option,sh_avgvol_o500,fa_div_none,cap_midover,ta_sma200_pa20&o=-volume

### 9. Recent Insider Buying + Flat/Down Week
https://finviz.com/screener.ashx?v=171&s=it_latestbuys&f=sh_opt_option,sh_avgvol_o500,fa_div_none,cap_midover,ta_perf_1w_d&o=-volume

### 10. Recent Insider Buying (all)
https://finviz.com/screener.ashx?v=131&s=it_latestbuys&f=sh_opt_option,sh_avgvol_o500,fa_div_none,cap_midover&o=-volume

### 11. Below 50-Day SMA, Above 200-Day SMA (pullback in uptrend)
https://finviz.com/screener.ashx?v=171&f=sh_opt_option,sh_avgvol_o500,fa_div_none,cap_midover,ta_sma50_pb,ta_sma200_pa&o=-volume

### 12. Oversold RSI
https://finviz.com/screener.ashx?v=171&s=ta_oversold&f=sh_opt_option,sh_avgvol_o500,fa_div_none,cap_midover&o=-volume

### 13. Unusual Volume + Optionable
https://finviz.com/screener.ashx?v=171&s=ta_unusualvolume&f=sh_opt_option,sh_avgvol_o500,fa_div_none,cap_midover&o=-volume

### 14. Most Volatile + Optionable
https://finviz.com/screener.ashx?v=171&s=ta_mostvolatile&f=sh_opt_option,sh_avgvol_o500,fa_div_none,cap_midover&o=-volume

### 15. Sector Laggard — Down Quarter, Good Margins, Low Debt
https://finviz.com/screener.ashx?v=161&f=sh_opt_option,sh_avgvol_o500,fa_div_none,cap_midover,fa_opermargin_pos,fa_debteq_u0.5,ta_perf_13w_d&o=-volume

### 16. Near 52-Week Low, Strong Fundamentals
https://finviz.com/screener.ashx?v=171&f=sh_opt_option,sh_avgvol_o500,fa_div_none,cap_midover,ta_highlow52w_b10l,fa_opermargin_pos,fa_curratio_o1.5&o=-volume

### 17. New Lows Signal
https://finviz.com/screener.ashx?v=171&s=ta_newlow&f=sh_opt_option,sh_avgvol_o500,fa_div_none,cap_midover&o=-volume

### 18. Recent Insider Selling on High Momentum (collar trigger)
https://finviz.com/screener.ashx?v=171&s=it_latestsales&f=sh_opt_option,sh_avgvol_o500,fa_div_none,cap_midover,ta_perf_4w_o10&o=-volume

### 19. Analyst Downgrade Signal
https://finviz.com/screener.ashx?v=171&s=ta_downgrades&f=sh_opt_option,sh_avgvol_o500,fa_div_none,cap_midover&o=-volume

### 20. Analyst Upgrade Signal
https://finviz.com/screener.ashx?v=171&s=ta_upgrades&f=sh_opt_option,sh_avgvol_o500,fa_div_none,cap_midover&o=-volume
