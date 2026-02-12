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
    fund_name: Mapped[Optional[str]] = mapped_column(String(500))
    issuer_name: Mapped[str] = mapped_column(String(500), nullable=False)
    strategy_text: Mapped[Optional[str]] = mapped_column(Text)
    filing_url: Mapped[Optional[str]] = mapped_column(String(1000))
    category: Mapped[Optional[str]] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_fetched: Mapped[Optional[datetime]] = mapped_column(DateTime)
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
    flow_data: Mapped[list["FlowData"]] = relationship(back_populates="etf")


class Holding(Base):
    __tablename__ = "holding"
    __table_args__ = (
        Index("holding_etf_report_idx", "etf_id", "report_date"),
        Index("holding_cusip_idx", "cusip"),
        Index("holding_report_date_idx", "report_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    etf_id: Mapped[int] = mapped_column(ForeignKey("etf.id"), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
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

    etf: Mapped["ETF"] = relationship(back_populates="holdings")


class Derivative(Base):
    __tablename__ = "derivative"
    __table_args__ = (
        Index("derivative_etf_report_idx", "etf_id", "report_date"),
        Index("derivative_report_date_idx", "report_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    etf_id: Mapped[int] = mapped_column(ForeignKey("etf.id"), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    derivative_type: Mapped[str] = mapped_column(String(20), nullable=False)
    underlying_name: Mapped[Optional[str]] = mapped_column(String(500))
    underlying_cusip: Mapped[Optional[str]] = mapped_column(String(9))
    notional_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2))
    counterparty: Mapped[Optional[str]] = mapped_column(String(500))
    counterparty_lei: Mapped[Optional[str]] = mapped_column(String(20))
    delta: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 6))
    expiration_date: Mapped[Optional[date]] = mapped_column(Date)

    etf: Mapped["ETF"] = relationship(back_populates="derivatives")


class Performance(Base):
    __tablename__ = "performance"
    __table_args__ = (
        UniqueConstraint("etf_id", "fiscal_year_end", name="performance_etf_fy_uniq"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    etf_id: Mapped[int] = mapped_column(ForeignKey("etf.id"), nullable=False)
    fiscal_year_end: Mapped[date] = mapped_column(Date, nullable=False)
    return_1yr: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 5))
    return_5yr: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 5))
    return_10yr: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 5))
    return_since_inception: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 5))
    benchmark_name: Mapped[Optional[str]] = mapped_column(String(500))
    benchmark_return_1yr: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 5))
    benchmark_return_5yr: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 5))
    benchmark_return_10yr: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 5))
    distribution_total: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))
    dist_ordinary_income: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))
    dist_qualified_dividend: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))
    dist_ltcg: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))
    dist_stcg: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))
    dist_return_of_capital: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))
    portfolio_turnover: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 5))
    expense_ratio_actual: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 5))

    etf: Mapped["ETF"] = relationship(back_populates="performances")


class FeeExpense(Base):
    __tablename__ = "fee_expense"
    __table_args__ = (
        UniqueConstraint(
            "etf_id", "effective_date", name="fee_expense_etf_date_uniq"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    etf_id: Mapped[int] = mapped_column(ForeignKey("etf.id"), nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    management_fee: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 5))
    distribution_12b1: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 5))
    other_expenses: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 5))
    total_expense_gross: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 5))
    fee_waiver: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 5))
    total_expense_net: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 5))

    etf: Mapped["ETF"] = relationship(back_populates="fee_expenses")


class FlowData(Base):
    __tablename__ = "flow_data"
    __table_args__ = (
        UniqueConstraint(
            "etf_id", "fiscal_year_end", name="flow_data_etf_fy_uniq"
        ),
        Index("flow_data_fy_idx", "fiscal_year_end"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    etf_id: Mapped[int] = mapped_column(ForeignKey("etf.id"), nullable=False)
    fiscal_year_end: Mapped[date] = mapped_column(Date, nullable=False)
    sales_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 4))
    redemptions_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 4))
    net_sales: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 4))

    etf: Mapped["ETF"] = relationship(back_populates="flow_data")
