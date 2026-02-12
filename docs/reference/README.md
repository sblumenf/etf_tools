# SEC EDGAR Reference Documentation

Downloaded 2026-02-11 from official SEC sources for use as parser development context.

## Contents

### Core Specs
| File | Source | Description |
|------|--------|-------------|
| `edgar-filer-manual-vol2.pdf` | [SEC](https://www.sec.gov/files/edgar/filermanual/efmvol2.pdf) | Definitive reference for all EDGAR submission types (v76) |
| `edgar-api-overview.pdf` | [SEC](https://www.sec.gov/files/edgar/filer-information/api-overview.pdf) | Overview of all EDGAR API endpoints (Dec 2025) |
| `edgar-xbrl-guide.pdf` | [SEC](https://www.sec.gov/files/edgar/filer-information/specifications/xbrl-guide.pdf) | XBRL filing guide (Jan 2026) |

### N-PORT (Form N-PORT-P)
| Directory/File | Description |
|----------------|-------------|
| `nport-xml-tech-spec-v1.7.html` | N-PORT XML Technical Specification page |
| `nport-xsd/EDGAR Form N-PORT XML Technical Specification.pdf` | Full PDF specification |
| `nport-xsd/EDGAR Form N-PORT XML schema files/` | XSD schemas: `eis_NPORT_Filer.xsd`, `eis_NPORT_common.xsd`, `eis_Common.xsd` |
| `nport-xsd/EDGAR Form N-PORT XML Sample files/` | 3 sample XML filings |
| `nport-xsd/EDGAR Form N-PORT Stylesheets/` | XSL stylesheets for rendering |

### XBRL Taxonomies

#### OEF — Open-End Fund (2025)
| File | Description |
|------|-------------|
| `xbrl-oef-2025/oef-2025.xsd` | Main OEF taxonomy schema |
| `xbrl-oef-2025/oef-rr-2025.xsd` | OEF Risk/Return combined schema |
| `xbrl-oef-2025/oef-sr-2025.xsd` | OEF Shareholder Report schema |
| `xbrl-oef-2025/oeftaxonomyguide-2025-03-17.pdf` | OEF taxonomy guide |

#### RR — Risk/Return Summary (2023)
| File | Description |
|------|-------------|
| `xbrl-rr-2023/rr-2023.xsd` | Main RR taxonomy schema |
| `xbrl-rr-2023/rr-preparers-guide-2022-11-04.pdf` | RR preparers guide |
| `xbrl-rr-2023/rr-samples/` | Sample iXBRL filings |

#### CEF — Closed-End Fund (2025)
| File | Description |
|------|-------------|
| `xbrl-cef-2025/cef-2025.xsd` | Main CEF taxonomy schema |

### 24F-2NT (Form 24F-2)
| Directory/File | Description |
|----------------|-------------|
| `24f2-xsd/.../EDGAR Form 24F-2 XML Technical Specification.pdf` | Full PDF specification (v2.1) |
| `24f2-xsd/.../EDGAR Form 24F-2 Schema Files/` | XSD schemas: `eis_24F_2NT_Filer.xsd`, `eis_Common.xsd`, `eis_Common_Fee.xsd` |
| `24f2-xsd/.../EDGAR Form 24F-2 XML Samples/` | 14 sample XML filings (N-1A, N-2, N-3, N-4, N-5, N-6, S-1/S-3, S-6 filer types) |
| `24f2-xsd/.../EDGAR Form 24F-2 Stylesheets/` | XSL stylesheets for rendering |

## Usage Notes

- **For NPORT-P parsing**: Start with the XSD schemas and sample XMLs. The `edgartools` library's `FundReport` class already handles most of this.
- **For N-CSR parsing**: Actual content is HTML/iXBRL using OEF taxonomy tags.
- **For 485BPOS parsing**: Uses iXBRL with RR (Risk/Return) taxonomy. The RR preparers guide explains tag usage.
- **For 24F-2NT parsing**: Pure XML since Feb 2022. Dedicated XSD schema — flow data is in `<item5>`. See `PARSER_REFERENCE_MAP.md` for field mappings.

## Context7 Availability

`edgartools` library docs (4,838 snippets) are available via Context7 at `/dgunning/edgartools`.
SEC filing format specs (this directory) are NOT on Context7 — they must be read from these local files.
