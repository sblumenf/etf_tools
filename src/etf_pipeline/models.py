from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ETF(Base):
    __tablename__ = "etf"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)
    cik: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    series_id: Mapped[Optional[str]] = mapped_column(String(20))
    class_id: Mapped[Optional[str]] = mapped_column(String(20), index=True)
    fund_name: Mapped[Optional[str]] = mapped_column(String(500))
    issuer_name: Mapped[str] = mapped_column(String(500), nullable=False)
    objective_text: Mapped[Optional[str]] = mapped_column(Text)
    strategy_text: Mapped[Optional[str]] = mapped_column(Text)
    principal_risks: Mapped[Optional[str]] = mapped_column(Text)
    filing_url: Mapped[Optional[str]] = mapped_column(String(1000))
    category: Mapped[Optional[str]] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    incomplete_data: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    holdings: Mapped[list["Holding"]] = relationship(back_populates="etf")
    derivatives: Mapped[list["Derivative"]] = relationship(back_populates="etf")
    performances: Mapped[list["Performance"]] = relationship(back_populates="etf")
    fee_expenses: Mapped[list["FeeExpense"]] = relationship(back_populates="etf")
    per_share_operating: Mapped[list["PerShareOperating"]] = relationship(
        back_populates="etf"
    )
    per_share_distributions: Mapped[list["PerShareDistribution"]] = relationship(
        back_populates="etf"
    )
    per_share_ratios: Mapped[list["PerShareRatios"]] = relationship(
        back_populates="etf"
    )
    monthly_returns: Mapped[list["NPORTMonthlyReturn"]] = relationship(
        back_populates="etf"
    )
    monthly_flows: Mapped[list["NPORTMonthlyFlow"]] = relationship(
        back_populates="etf"
    )
    interest_rate_risks: Mapped[list["InterestRateRisk"]] = relationship(
        back_populates="etf"
    )
    credit_spread_risks: Mapped[list["CreditSpreadRisk"]] = relationship(
        back_populates="etf"
    )


class Holding(Base):
    __tablename__ = "holding"
    __table_args__ = (
        UniqueConstraint(
            "etf_id", "report_date", "holding_key", "filing_date", name="holding_uniq"
        ),
        Index("holding_etf_report_idx", "etf_id", "report_date"),
        Index("holding_cusip_idx", "cusip"),
        Index("holding_report_date_idx", "report_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    etf_id: Mapped[int] = mapped_column(ForeignKey("etf.id"), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    filing_date: Mapped[date] = mapped_column(Date, nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    cusip: Mapped[Optional[str]] = mapped_column(String(9))
    isin: Mapped[Optional[str]] = mapped_column(String(12))
    ticker: Mapped[Optional[str]] = mapped_column(String(20))
    lei: Mapped[Optional[str]] = mapped_column(String(20))
    balance: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 4))
    units: Mapped[Optional[str]] = mapped_column(String(20))
    value_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2))
    pct_val: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 5))
    asset_category: Mapped[Optional[str]] = mapped_column(String(20))
    issuer_category: Mapped[Optional[str]] = mapped_column(String(50))
    country: Mapped[Optional[str]] = mapped_column(String(3))
    currency: Mapped[Optional[str]] = mapped_column(String(3))
    fair_value_level: Mapped[Optional[int]] = mapped_column(Integer)
    is_restricted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(500))
    payoff_profile: Mapped[Optional[str]] = mapped_column(String(10))
    exchange_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))
    holding_key: Mapped[str] = mapped_column(String(500), nullable=False)
    borrower_name: Mapped[Optional[str]] = mapped_column(String(500))
    liquidity_classification: Mapped[Optional[str]] = mapped_column(String(50))

    etf: Mapped["ETF"] = relationship(back_populates="holdings")
    debt_security_detail: Mapped[Optional["DebtSecurityDetail"]] = relationship(
        back_populates="holding", cascade="all, delete-orphan", uselist=False
    )
    security_lending: Mapped[Optional["SecurityLending"]] = relationship(
        back_populates="holding", cascade="all, delete-orphan", uselist=False
    )


class Derivative(Base):
    __tablename__ = "derivative"
    __table_args__ = (
        UniqueConstraint(
            "etf_id",
            "report_date",
            "derivative_type",
            "underlying_name",
            "filing_date",
            "counterparty",
            name="derivative_uniq",
        ),
        Index("derivative_etf_report_idx", "etf_id", "report_date"),
        Index("derivative_report_date_idx", "report_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    etf_id: Mapped[int] = mapped_column(ForeignKey("etf.id"), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    filing_date: Mapped[date] = mapped_column(Date, nullable=False)
    derivative_type: Mapped[str] = mapped_column(String(20), nullable=False)
    underlying_name: Mapped[Optional[str]] = mapped_column(String(500))
    underlying_cusip: Mapped[Optional[str]] = mapped_column(String(9))
    notional_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2))
    counterparty: Mapped[Optional[str]] = mapped_column(String(500))
    counterparty_lei: Mapped[Optional[str]] = mapped_column(String(20))
    delta: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 6))
    expiration_date: Mapped[Optional[date]] = mapped_column(Date)
    currency_sold: Mapped[Optional[str]] = mapped_column(String(3))
    currency_amt_sold: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    settlement_date: Mapped[Optional[date]] = mapped_column(Date)
    written_notional_amt: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    other_amt: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))

    # New shared fields (US-1)
    unrealized_appreciation: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2))
    currency: Mapped[Optional[str]] = mapped_column(String(3))
    underlying_title: Mapped[Optional[str]] = mapped_column(String(150))
    underlying_lei: Mapped[Optional[str]] = mapped_column(String(20))
    underlying_isin: Mapped[Optional[str]] = mapped_column(String(12))
    underlying_ticker: Mapped[Optional[str]] = mapped_column(String(20))
    underlying_other_id: Mapped[Optional[str]] = mapped_column(String(50))
    underlying_other_id_type: Mapped[Optional[str]] = mapped_column(String(50))
    underlying_balance: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 4))
    underlying_units: Mapped[Optional[str]] = mapped_column(String(50))
    underlying_currency: Mapped[Optional[str]] = mapped_column(String(3))
    underlying_value_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2))
    underlying_pct_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 5))
    underlying_asset_cat: Mapped[Optional[str]] = mapped_column(String(20))
    underlying_issuer_cat: Mapped[Optional[str]] = mapped_column(String(20))
    underlying_inv_country: Mapped[Optional[str]] = mapped_column(String(2))
    payoff_profile: Mapped[Optional[str]] = mapped_column(String(10))

    etf: Mapped["ETF"] = relationship(back_populates="derivatives")
    swap: Mapped[Optional["DerivativeSwap"]] = relationship(
        back_populates="derivative", cascade="all, delete-orphan", uselist=False
    )
    option: Mapped[Optional["DerivativeOption"]] = relationship(
        back_populates="derivative", cascade="all, delete-orphan", uselist=False
    )


class DerivativeSwap(Base):
    """Swap-specific derivative details. One row per swap derivative."""
    __tablename__ = "derivative_swap"
    __table_args__ = (
        Index("derivative_swap_derivative_idx", "derivative_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    derivative_id: Mapped[int] = mapped_column(
        ForeignKey("derivative.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    upfront_payment: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2))
    upfront_payment_currency: Mapped[Optional[str]] = mapped_column(String(3))
    upfront_receipt: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2))
    upfront_receipt_currency: Mapped[Optional[str]] = mapped_column(String(3))
    swap_flag: Mapped[Optional[str]] = mapped_column(String(1))

    derivative: Mapped["Derivative"] = relationship(back_populates="swap")
    legs: Mapped[list["DerivativeSwapLeg"]] = relationship(
        back_populates="swap", cascade="all, delete-orphan"
    )


class DerivativeSwapLeg(Base):
    """Swap leg (pay or receive). Two rows per swap."""
    __tablename__ = "derivative_swap_leg"
    __table_args__ = (
        UniqueConstraint("swap_id", "direction", name="swap_leg_uniq"),
        Index("derivative_swap_leg_swap_idx", "swap_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    swap_id: Mapped[int] = mapped_column(
        ForeignKey("derivative_swap.id", ondelete="CASCADE"), nullable=False
    )
    direction: Mapped[str] = mapped_column(String(7), nullable=False)  # "pay" or "receive"
    leg_type: Mapped[Optional[str]] = mapped_column(String(10))  # "fixed", "floating", "other"

    # Fixed leg fields
    fixed_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 6))
    fixed_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2))
    fixed_currency: Mapped[Optional[str]] = mapped_column(String(3))

    # Floating leg fields
    floating_index: Mapped[Optional[str]] = mapped_column(String(100))
    floating_spread: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 6))
    floating_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2))
    floating_currency: Mapped[Optional[str]] = mapped_column(String(3))
    tenor: Mapped[Optional[str]] = mapped_column(String(20))
    tenor_unit: Mapped[Optional[str]] = mapped_column(String(10))
    reset_date_tenor: Mapped[Optional[str]] = mapped_column(String(20))
    reset_date_unit: Mapped[Optional[str]] = mapped_column(String(10))

    # Other leg type
    other_description: Mapped[Optional[str]] = mapped_column(Text)

    swap: Mapped["DerivativeSwap"] = relationship(back_populates="legs")


class DerivativeOption(Base):
    """Option-specific derivative details. One row per option, swaption, or warrant."""
    __tablename__ = "derivative_option"
    __table_args__ = (
        Index("derivative_option_derivative_idx", "derivative_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    derivative_id: Mapped[int] = mapped_column(
        ForeignKey("derivative.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    put_or_call: Mapped[Optional[str]] = mapped_column(String(4))
    written_or_purchased: Mapped[Optional[str]] = mapped_column(String(10))
    share_number: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 4))
    exercise_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6))
    exercise_price_currency: Mapped[Optional[str]] = mapped_column(String(3))
    index_name: Mapped[Optional[str]] = mapped_column(String(150))
    index_identifier: Mapped[Optional[str]] = mapped_column(String(50))
    nested_deriv_type: Mapped[Optional[str]] = mapped_column(String(20))
    nested_deriv_notional: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2))
    nested_deriv_counterparty: Mapped[Optional[str]] = mapped_column(String(500))
    nested_deriv_currency: Mapped[Optional[str]] = mapped_column(String(3))

    derivative: Mapped["Derivative"] = relationship(back_populates="option")


class DebtSecurityDetail(Base):
    __tablename__ = "debt_security_detail"
    __table_args__ = (
        UniqueConstraint("holding_id", name="debt_security_detail_holding_uniq"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    holding_id: Mapped[int] = mapped_column(
        ForeignKey("holding.id", ondelete="CASCADE"), nullable=False
    )
    maturity_date: Mapped[Optional[date]] = mapped_column(Date)
    coupon_kind: Mapped[Optional[str]] = mapped_column(String(50))
    annualized_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 6))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_in_arrears: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_paid_kind: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_mandatory_convertible: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    is_contingent_convertible: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    holding: Mapped["Holding"] = relationship(back_populates="debt_security_detail")


class SecurityLending(Base):
    __tablename__ = "security_lending"
    __table_args__ = (
        UniqueConstraint("holding_id", name="security_lending_holding_uniq"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    holding_id: Mapped[int] = mapped_column(
        ForeignKey("holding.id", ondelete="CASCADE"), nullable=False
    )
    is_cash_collateral: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    is_non_cash_collateral: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    is_loan_by_fund: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    holding: Mapped["Holding"] = relationship(back_populates="security_lending")


class Performance(Base):
    __tablename__ = "performance"
    __table_args__ = (
        UniqueConstraint(
            "etf_id", "fiscal_year_end", "filing_date", name="performance_etf_fy_uniq"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    etf_id: Mapped[int] = mapped_column(ForeignKey("etf.id"), nullable=False)
    fiscal_year_end: Mapped[date] = mapped_column(Date, nullable=False)
    filing_date: Mapped[date] = mapped_column(Date, nullable=False)
    return_1yr: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 5))
    return_5yr: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 5))
    return_10yr: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 5))
    return_since_inception: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 5))
    benchmark_name: Mapped[Optional[str]] = mapped_column(String(500))
    benchmark_return_1yr: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 5))
    benchmark_return_5yr: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 5))
    benchmark_return_10yr: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 5))
    portfolio_turnover: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 5))
    expense_ratio_actual: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 5))

    etf: Mapped["ETF"] = relationship(back_populates="performances")


class FeeExpense(Base):
    __tablename__ = "fee_expense"
    __table_args__ = (
        UniqueConstraint(
            "etf_id", "effective_date", "filing_date", name="fee_expense_etf_date_uniq"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    etf_id: Mapped[int] = mapped_column(ForeignKey("etf.id"), nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    filing_date: Mapped[date] = mapped_column(Date, nullable=False)
    management_fee: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 5))
    distribution_12b1: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 5))
    other_expenses: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 5))
    total_expense_gross: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 5))
    fee_waiver: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 5))
    total_expense_net: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 5))
    acquired_fund_fees: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 5))
    fee_waiver_expiration_date: Mapped[Optional[date]] = mapped_column(Date)

    etf: Mapped["ETF"] = relationship(back_populates="fee_expenses")


class FlowData(Base):
    __tablename__ = "flow_data"
    __table_args__ = (
        UniqueConstraint(
            "cik", "fiscal_year_end", "filing_date", name="flow_data_cik_fy_uniq"
        ),
        Index("flow_data_fy_idx", "fiscal_year_end"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cik: Mapped[str] = mapped_column(String(10), nullable=False)
    fiscal_year_end: Mapped[date] = mapped_column(Date, nullable=False)
    filing_date: Mapped[date] = mapped_column(Date, nullable=False)
    sales_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 4))
    redemptions_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 4))
    net_sales: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 4))


class PerShareOperating(Base):
    __tablename__ = "per_share_operating"
    __table_args__ = (
        UniqueConstraint(
            "etf_id",
            "fiscal_year_end",
            "filing_date",
            name="per_share_operating_etf_fy_uniq",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    etf_id: Mapped[int] = mapped_column(ForeignKey("etf.id"), nullable=False)
    fiscal_year_end: Mapped[date] = mapped_column(Date, nullable=False)
    filing_date: Mapped[date] = mapped_column(Date, nullable=False)
    nav_beginning: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))
    net_investment_income: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))
    net_realized_unrealized_gain: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 4)
    )
    total_from_operations: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))
    equalization: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))
    nav_end: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))
    total_return: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 5))
    math_validated: Mapped[bool] = mapped_column(Boolean, nullable=False)

    etf: Mapped["ETF"] = relationship(back_populates="per_share_operating")


class PerShareDistribution(Base):
    __tablename__ = "per_share_distribution"
    __table_args__ = (
        UniqueConstraint(
            "etf_id",
            "fiscal_year_end",
            "filing_date",
            name="per_share_distribution_etf_fy_uniq",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    etf_id: Mapped[int] = mapped_column(ForeignKey("etf.id"), nullable=False)
    fiscal_year_end: Mapped[date] = mapped_column(Date, nullable=False)
    filing_date: Mapped[date] = mapped_column(Date, nullable=False)
    dist_net_investment_income: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 4)
    )
    dist_realized_gains: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))
    dist_return_of_capital: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))
    dist_total: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))

    etf: Mapped["ETF"] = relationship(back_populates="per_share_distributions")


class PerShareRatios(Base):
    __tablename__ = "per_share_ratios"
    __table_args__ = (
        UniqueConstraint(
            "etf_id",
            "fiscal_year_end",
            "filing_date",
            name="per_share_ratios_etf_fy_uniq",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    etf_id: Mapped[int] = mapped_column(ForeignKey("etf.id"), nullable=False)
    fiscal_year_end: Mapped[date] = mapped_column(Date, nullable=False)
    filing_date: Mapped[date] = mapped_column(Date, nullable=False)
    expense_ratio: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 5))
    portfolio_turnover: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 5))
    net_assets_end: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2))

    etf: Mapped["ETF"] = relationship(back_populates="per_share_ratios")


class FundSnapshot(Base):
    __tablename__ = "fund_snapshot"
    __table_args__ = (
        UniqueConstraint(
            "cik", "report_date", "filing_date", name="fund_snapshot_cik_date_uniq"
        ),
        Index("fund_snapshot_cik_idx", "cik"),
        Index("fund_snapshot_report_date_idx", "report_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cik: Mapped[str] = mapped_column(String(10), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    filing_date: Mapped[date] = mapped_column(Date, nullable=False)
    total_assets: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2))
    total_liabilities: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2))
    net_assets: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2))
    cash_not_reported: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2))
    assets_invested: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2))
    assets_misc_sec: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2))
    amt_pay_one_yr_banks_borr: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2))
    amt_pay_one_yr_ctrld_comp: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2))
    amt_pay_one_yr_oth_affil: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2))
    amt_pay_one_yr_other: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2))
    amt_pay_aft_one_yr_banks_borr: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2))
    amt_pay_aft_one_yr_ctrld_comp: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2))
    amt_pay_aft_one_yr_oth_affil: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2))
    amt_pay_aft_one_yr_other: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2))
    delay_deliv: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2))
    stand_by_commit: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2))
    liquidity_pref: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2))
    is_non_cash_collateral: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class NPORTMonthlyReturn(Base):
    __tablename__ = "nport_monthly_return"
    __table_args__ = (
        UniqueConstraint(
            "etf_id", "report_date", "class_id", "filing_date", name="nport_monthly_return_uniq"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    etf_id: Mapped[int] = mapped_column(ForeignKey("etf.id"), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    filing_date: Mapped[date] = mapped_column(Date, nullable=False)
    class_id: Mapped[Optional[str]] = mapped_column(String(10))
    month_1_return: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 2))
    month_2_return: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 2))
    month_3_return: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 2))

    etf: Mapped["ETF"] = relationship(back_populates="monthly_returns")


class NPORTMonthlyFlow(Base):
    __tablename__ = "nport_monthly_flow"
    __table_args__ = (
        UniqueConstraint(
            "etf_id", "report_date", "class_id", "filing_date", name="nport_monthly_flow_uniq"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    etf_id: Mapped[int] = mapped_column(ForeignKey("etf.id"), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    filing_date: Mapped[date] = mapped_column(Date, nullable=False)
    class_id: Mapped[Optional[str]] = mapped_column(String(50))
    month_1_sales: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    month_1_redemptions: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    month_1_reinvestments: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    month_2_sales: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    month_2_redemptions: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    month_2_reinvestments: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    month_3_sales: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    month_3_redemptions: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    month_3_reinvestments: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))

    etf: Mapped["ETF"] = relationship(back_populates="monthly_flows")


class InterestRateRisk(Base):
    __tablename__ = "interest_rate_risk"
    __table_args__ = (
        UniqueConstraint(
            "etf_id", "report_date", "currency_code", "filing_date", name="interest_rate_risk_uniq"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    etf_id: Mapped[int] = mapped_column(ForeignKey("etf.id"), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    filing_date: Mapped[date] = mapped_column(Date, nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    dv01_3m: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 2))
    dv01_1y: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 2))
    dv01_5y: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 2))
    dv01_10y: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 2))
    dv01_30y: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 2))
    dv100_3m: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 2))
    dv100_1y: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 2))
    dv100_5y: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 2))
    dv100_10y: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 2))
    dv100_30y: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 2))

    etf: Mapped["ETF"] = relationship(back_populates="interest_rate_risks")


class CreditSpreadRisk(Base):
    __tablename__ = "credit_spread_risk"
    __table_args__ = (
        UniqueConstraint(
            "etf_id", "report_date", "filing_date", name="credit_spread_risk_uniq"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    etf_id: Mapped[int] = mapped_column(ForeignKey("etf.id"), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    filing_date: Mapped[date] = mapped_column(Date, nullable=False)
    invst_grade_3m: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 2))
    invst_grade_1y: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 2))
    invst_grade_5y: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 2))
    invst_grade_10y: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 2))
    invst_grade_30y: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 2))
    non_invst_grade_3m: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 2))
    non_invst_grade_1y: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 2))
    non_invst_grade_5y: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 2))
    non_invst_grade_10y: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 2))
    non_invst_grade_30y: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 2))

    etf: Mapped["ETF"] = relationship(back_populates="credit_spread_risks")


class ProcessingLog(Base):
    __tablename__ = "processing_log"
    __table_args__ = (
        UniqueConstraint("cik", "parser_type", name="processing_log_cik_parser_uniq"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cik: Mapped[str] = mapped_column(String(10), nullable=False)
    parser_type: Mapped[str] = mapped_column(String(20), nullable=False)
    last_run_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    latest_filing_date_seen: Mapped[date] = mapped_column(Date, nullable=False)
