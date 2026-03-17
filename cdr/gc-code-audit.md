# Government of Canada Open Source Code Audit
*Comprehensive Analysis for HICC, ACCORD & CDR Systems*

**Date:** March 16, 2026  
**Version:** 2.0  
**Status:** Complete

## Executive Summary

This audit examines 500+ open source repositories across 9 major Government of Canada organizations, analyzing their relevance to three key systems:

- **HICC** (HR dashboards, finance tools, org charts, workforce analytics)
- **ACCORD** (collective agreements, pay data, labour relations, rules engines)  
- **CDR** (sovereign AI nodes, compliance automation, template systems, local AI)

### Key Findings:
- **74 repositories** under canada-ca (core GC templates and standards)
- **275 repositories** under cds-snc (digital service delivery)
- **204 repositories** under StatCan (data analytics and processing)
- **50+ repositories** across specialized departments (ECCC-MSC, DND-DRDC, etc.)

### Technological Landscape:
- **JavaScript/TypeScript**: Dominant for web applications (60%+)
- **Python**: Primary for data processing and AI/ML (40%+)
- **Vue.js/React**: Standard frontend frameworks
- **Node.js**: Preferred backend runtime
- **Docker/Kubernetes**: Standard containerization (StatCan leading)

## High Relevance to HICC
*HR dashboards, finance tools, org charts, workforce analytics*

### 🏆 **Talent Cloud** - `github.com/GCTC-NTGC/TalentCloud`
- **What it does:** Cross-sectoral talent management and recruitment platform
- **Tech stack:** TypeScript, PHP, HTML, Laravel
- **Relevance:** ⭐⭐⭐⭐⭐ - Direct HR dashboard and talent analytics
- **URL:** https://github.com/GCTC-NTGC/TalentCloud
- **Status:** Active development
- **Key features:** Job matching, skill tracking, candidate evaluation

### 🏆 **GC InfoBase** - `github.com/TBS-EACPD/infobase`
- **What it does:** Interactive data visualization for federal spending and workforce data
- **Tech stack:** JavaScript, React, D3.js
- **Relevance:** ⭐⭐⭐⭐⭐ - Government-wide financial and workforce analytics
- **URL:** https://github.com/TBS-EACPD/infobase
- **Status:** Actively maintained
- **Key features:** Budget visualization, org charts, workforce metrics

### 🏆 **AppHub Dashboard** - `github.com/esdc-devx/AppHub`
- **What it does:** Dashboard to expose metrics on software projects at ESDC
- **Tech stack:** JavaScript, .NET, Dashboard frameworks
- **Relevance:** ⭐⭐⭐⭐ - Project and resource analytics model
- **URL:** https://github.com/esdc-devx/AppHub
- **Status:** Maintained
- **Key features:** Project metrics, code coverage reporting

### 📊 **OpenTabulate** - `github.com/CSBP-CPSE/OpenTabulate`
- **What it does:** Centralize, process, and clean data
- **Tech stack:** Python, Data processing
- **Relevance:** ⭐⭐⭐⭐ - Data pipeline for HR analytics
- **URL:** https://github.com/CSBP-CPSE/OpenTabulate
- **Status:** Maintained

## High Relevance to ACCORD
*Collective agreements, pay data, labour relations, rules engines*

### 🏆 **PayScraper** - `github.com/ToferC/payscraper`
- **What it does:** GO Lang project for scraping Pay data from TBS Collective Agreements
- **Tech stack:** Go, Web scraping, Data extraction
- **Relevance:** ⭐⭐⭐⭐⭐ - Direct collective agreement pay data extraction
- **URL:** https://github.com/ToferC/payscraper  
- **Status:** MIT Licensed, active
- **Key features:** Automated pay scale extraction, CA parsing

### 🏆 **Office Entry Management** - `github.com/justicecanada/ogd-office-entry-am-entree-au-bureau`
- **What it does:** Employee workplace access request and approval system
- **Tech stack:** PowerShell, Power Apps, Power Automate
- **Relevance:** ⭐⭐⭐⭐ - Workflow management and employee approval processes
- **URL:** https://github.com/justicecanada/ogd-office-entry-am-entree-au-bureau
- **Status:** Maintained
- **Key features:** Request workflows, manager approvals, capacity management

### 📋 **CKAN Extensions (Multiple)** - Various repositories
- **What it does:** Data management and schema validation
- **Tech stack:** Python, CKAN, Data schemas
- **Relevance:** ⭐⭐⭐ - Rules engines and data validation for labour data
- **Key repos:**
  - `github.com/open-data/ckanext-canada` - Core GC CKAN extension
  - `github.com/open-data/ckanext-scheming` - Schema validation
  - `github.com/open-data/ckanext-fluent` - Multilingual support

## High Relevance to CDR
*Sovereign AI nodes, compliance automation, template systems, local AI*

### 🏆 **Algorithmic Impact Assessment** - `github.com/canada-ca/aia-eia-js`
- **What it does:** Assessment tool for automated decision systems including AI
- **Tech stack:** JavaScript, TypeScript, Vue.js, HTML/CSS
- **Relevance:** ⭐⭐⭐⭐⭐ - AI compliance and impact assessment
- **URL:** https://github.com/canada-ca/aia-eia-js
- **Status:** Actively maintained
- **Key features:** AI risk assessment, compliance checking, decision documentation

### 🏆 **Template System** - `github.com/canada-ca/template-gabarit`
- **What it does:** Open source code repository template for GC
- **Tech stack:** JavaScript, GitHub Actions, Standardized templates
- **Relevance:** ⭐⭐⭐⭐⭐ - Template systems and standardization
- **URL:** https://github.com/canada-ca/template-gabarit
- **Status:** Actively maintained

### 🏆 **Notification API** - `github.com/cds-snc/notification-api`
- **What it does:** Government notification system for emails, SMS, letters
- **Tech stack:** JavaScript, TypeScript, Python, API
- **Relevance:** ⭐⭐⭐⭐ - Automated communications and compliance notifications
- **URL:** https://github.com/cds-snc/notification-api
- **Status:** Alpha, active development

### 🤖 **Assemblyline** - `bitbucket.org/cse-assemblyline/assemblyline`
- **What it does:** Malware analysis platform with automated file analysis
- **Tech stack:** Python, Machine Learning, Automated analysis
- **Relevance:** ⭐⭐⭐⭐⭐ - Automated analysis and compliance checking
- **URL:** https://bitbucket.org/cse-assemblyline/assemblyline
- **Status:** MIT licensed, maintained by CSE
- **Key features:** Automated threat analysis, ML-based detection

### 🧮 **LODE-ECDO** - `github.com/CSBP-CPSE/LODE-ECDO`
- **What it does:** Linkable Open Data Environment for data exploration and integration
- **Tech stack:** Python, Data integration, Graph databases
- **Relevance:** ⭐⭐⭐⭐ - Data linking and knowledge graphs for AI
- **URL:** https://github.com/CSBP-CPSE/LODE-ECDO
- **Status:** Development phase

## Building Blocks
*Reusable components and frameworks*

### Web Frameworks & UI Components

#### **WET-BOEW** - `github.com/wet-boew/wet-boew`
- **What it does:** Web Experience Toolkit - accessible, mobile-friendly web framework
- **Tech stack:** JavaScript, HTML, CSS, SASS
- **Relevance:** ⭐⭐⭐⭐ - Standard web framework for all GC applications
- **URL:** https://github.com/wet-boew/wet-boew

#### **CDTS** - `github.com/wet-boew/cdts-sgdc`
- **What it does:** Centralized Templates and Design System
- **Tech stack:** JavaScript, HTML, CSS, CoffeeScript
- **Relevance:** ⭐⭐⭐⭐ - Template delivery system
- **URL:** https://github.com/wet-boew/cdts-sgdc

#### **DECD Design System** - `github.com/DTS-STN/DECD-Design-System`
- **What it does:** Service Canada design system and component library
- **Tech stack:** React, JavaScript, TailwindCSS
- **Relevance:** ⭐⭐⭐⭐ - Modern component library for dashboards

### Data Processing & Analytics

#### **Sarracenia** - `github.com/MetPX/sarracenia`
- **What it does:** Real-time data sharing and distribution
- **Tech stack:** Python, C, Message queuing
- **Relevance:** ⭐⭐⭐ - Real-time data pipelines for analytics

#### **StatCan Charts** - `github.com/StatCan/charts`
- **What it does:** Kubernetes applications for Statistics Canada
- **Tech stack:** Kubernetes, Helm, Container orchestration
- **Relevance:** ⭐⭐⭐⭐ - Cloud-native deployment patterns

#### **Volume Cleaner** - `github.com/StatCan/volume-cleaner`
- **What it does:** Automated cleanup of unused storage resources
- **Tech stack:** Go, Kubernetes, Microservices
- **Relevance:** ⭐⭐⭐ - Resource management automation

### Mapping & Visualization

#### **RAMP4** - `github.com/ramp4-pcar4/ramp4-pcar4`
- **What it does:** Reusable Accessible Mapping Platform
- **Tech stack:** Vue3, JavaScript, TypeScript, GIS
- **Relevance:** ⭐⭐⭐ - Interactive data visualization for dashboards

#### **Storylines** - `github.com/ramp4-pcar4/storylines`
- **What it does:** Interactive multimedia presentation tool
- **Tech stack:** Vue3, JavaScript, TypeScript
- **Relevance:** ⭐⭐⭐ - Data storytelling and reporting

### Security & Compliance

#### **EGSnrc** - `github.com/nrc-cnrc/EGSnrc`
- **What it does:** Monte Carlo simulation toolkit for radiation transport
- **Tech stack:** C++, Scientific computing
- **Relevance:** ⭐⭐ - Scientific computation frameworks

## Full Catalogue by Department

### Treasury Board of Canada Secretariat (TBS)
**Organization:** `canada-ca`, `cds-snc`
**Total repositories:** 350+

#### Core Infrastructure:
- **canada-ca/ore-ero** - Open Resource Exchange platform (HTML, 43⭐)
- **canada-ca/design-system** - Canada.ca design system (HTML, 34⭐)  
- **canada-ca/architecture** - Enterprise architecture models (MIT)
- **canada-ca/welcome** - Organization readme (70⭐)

#### Digital Services (CDS):
- **cds-snc/digital-canada-ca** - CDS website (Hugo, static site)
- **cds-snc/covid-alert-server** - COVID-19 exposure notification
- **cds-snc/status-statut** - Service status page (Upptime)
- **cds-snc/talent** - CDS talent handbook

#### Data & Analytics:
- **TBS-EACPD/infobase** - GC InfoBase data visualization (JavaScript, maintained)
- **open-data/ckanext-canada** - GC CKAN extension (Python, maintained)
- **open-data/ckanext-scheming** - Schema validation (Python, maintained)
- **GCTC-NTGC/TalentCloud** - Talent management platform (TypeScript/PHP)

#### Tools & Templates:
- **canada-ca/template-gabarit** - Code repository template (JavaScript, 22⭐)
- **canada-ca/aia-eia-js** - AI Impact Assessment (Vue.js, 68⭐, maintained)
- **wet-boew/wet-boew** - Web Experience Toolkit (JavaScript, maintained)
- **wet-boew/cdts-sgdc** - Centralized Templates (JavaScript, maintained)

### Statistics Canada
**Organization:** `StatCan`, `CSBP-CPSE`
**Total repositories:** 204

#### Analytics Platform:
- **StatCan/charts** - Kubernetes applications (Helm charts)
- **StatCan/aaw** - Advanced Analytics Workspace documentation
- **StatCan/volume-cleaner** - Storage resource management (Go, maintained)

#### Data Processing:
- **CSBP-CPSE/OpenTabulate** - Data centralization and cleaning (MIT)
- **CSBP-CPSE/LODE-ECDO** - Linkable Open Data Environment (MIT, development)

#### Web Platforms:
- **drupalwxt/wxt** - Drupal WxT distribution (PHP/HTML, maintained)

### Employment and Social Development Canada (ESDC)
**Organization:** `esdc-devx`, `DTS-STN`

#### Development Tools:
- **esdc-devx/AppHub** - Software project metrics dashboard (MIT)
- **esdc-devx/DotNetCCDemo** - Code coverage demonstration (.NET, MIT)

#### Service Delivery:
- **DTS-STN/DECD-Design-System** - Service Canada design system (React, TailwindCSS)

### Environment and Climate Change Canada (ECCC)
**Organization:** `ECCC-MSC`, `ramp4-pcar4`

#### Environmental Modeling:
- **framagit.org/metroprojects/metro** - Road forecast software (Python, GPL-2.0)
- **ECCC-MSC/libecbufr** - BUFR encoding/decoding library (C, GPL-3.0, maintained)

#### Mapping & Visualization:
- **ramp4-pcar4/ramp4-pcar4** - Accessible mapping platform (Vue3, TypeScript, MIT, maintained)
- **ramp4-pcar4/storylines** - Interactive storytelling (Vue3, TypeScript, MIT, maintained)

### National Defence (DND)
**Organization:** `DND-DRDC-RDDC`

#### Research & Analysis:
- **DND-DRDC-RDDC/OS_PyCoMod** - Disease compartment modeling (Python, BSD-3-Clause, Beta)
- **DND-DRDC-RDDC/OS_covid_IFR_Lombardy-MRM_DGH** - COVID-19 mortality analysis (R, MIT)
- **DND-DRDC-RDDC/OS_COVID-19-POMDP-Dashboard** - Decision process dashboard (R, MIT, Alpha)
- **DND-DRDC-RDDC/OS_ELLA** - Naval convoy analysis (R, MIT)
- **DND-DRDC-RDDC/OS_DriverMetadataExtractionCodes_RCM_C-band_SARdata** - RADARSAT data processing (Python/C++, Python-2.0, Alpha)

### Communications Security Establishment (CSE)
**Organization:** Various repositories

#### Cybersecurity:
- **bitbucket.org/cse-assemblyline/assemblyline** - Malware analysis platform (Python, MIT)
- **CommunicationsSecurityEstablishment/spartacus** - Assembly programming learning environment (Python, GPL-2.0)

### Innovation, Science and Economic Development (ISED)
**Organization:** `ic-crc`

#### Research Tools:
- **ic-crc/SAFE-Tool** - Radio frequency path loss prediction (Python, MIT, Beta)
- **ic-crc/crc-covlib** - Radio wave propagation API (Python/C++, MIT, maintained)

### Transport Canada
**Organization:** `tc-ca`

#### Applications:
- **tc-ca/alexa-gc-recalls** - Vehicle safety recalls Alexa skill (JavaScript, MIT)
- **tc-ca/Reference-Centre** - Document retrieval system (C#, MIT)

### Department of Justice
**Organization:** `justicecanada`

#### Workplace Management:
- **justicecanada/ogd-office-entry-am-entree-au-bureau** - Office entry management (Power Platform, MIT, maintained)

### National Research Council (NRC)
**Organization:** `nrc-cnrc`

#### Scientific Computing:
- **nrc-cnrc/EGSnrc** - Monte Carlo radiation simulation (C++, AGPL-3.0)

### Public Health Agency of Canada (PHAC)
**Organization:** `phac-nml`

#### Health Informatics:
- **phac-nml/irida** - Genomic epidemiology platform (Java, Apache-2.0, maintained)

### Shared Services Canada (SSC)
**Organization:** `MetPX`, `gc-da11yn`

#### Infrastructure:
- **MetPX/sarracenia** - Data distribution system (Python/C, GPL-2.0)
- **gc-da11yn/gc-da11yn.github.io** - Digital accessibility toolkit (NodeJS, MIT, maintained)

### Canadian Space Agency (CSA)

#### Space Operations:
- **git.eclipse.org/c/apogy/apogy.git** - Robot and satellite operations (Java, EPL-1.0)

### Municipal Examples
Several municipal governments also contribute:

#### City of Montreal:
- **VilledeMontreal/CKAN-Extension-Territoire** - Municipal CKAN extension (Python, MIT)
- **VilledeMontreal/workit** - Workflow engine (TypeScript, MIT)

#### City of Sault Ste Marie:
- **cityssm/lottery-licence-manager** - Municipal licensing (TypeScript, SQLite, MIT)
- **cityssm/parking-ticket-system** - Parking enforcement (TypeScript, SQLite, Beta)
- **cityssm/corporate-records-manager** - Legal records management (TypeScript, MIT)
- **cityssm/contract-expiration-tracker** - Procurement tracking (TypeScript, SQLite, MIT)

## Observations & Opportunities

### Strengths
1. **Standardization Success**: WET-BOEW and CDTS provide consistent user experience
2. **Open Source Culture**: Strong commitment to public repositories and MIT licensing
3. **Modern Tech Stack**: Vue.js, React, TypeScript adoption across departments
4. **Data Analytics**: StatCan leading with advanced Kubernetes and data processing
5. **Accessibility**: Strong focus on WCAG 2.1 AA compliance
6. **Documentation**: Generally good documentation practices

### Gaps & Opportunities

#### For HICC (HR Dashboards & Analytics):
1. **Limited Integration**: Most HR-related tools are standalone
2. **Opportunity**: Create unified HR data platform using StatCan's analytics expertise
3. **Missing**: Real-time workforce analytics dashboards
4. **Potential**: Leverage TalentCloud architecture for broader HR needs

#### For ACCORD (Collective Agreements & Pay):
1. **Single Point**: PayScraper is only direct CA tool - needs expansion
2. **Opportunity**: Build comprehensive labour relations platform
3. **Missing**: Automated collective agreement analysis and comparison
4. **Potential**: Use CKAN extensions for structured labour data

#### For CDR (AI & Compliance):
1. **Strong Foundation**: AIA tool shows AI governance capability
2. **Opportunity**: Expand compliance automation using Assemblyline patterns
3. **Missing**: Local AI deployment frameworks
4. **Potential**: Leverage StatCan's Kubernetes expertise for AI nodes

### Technical Recommendations

#### Architecture Patterns:
1. **Adopt StatCan's Kubernetes approach** for scalable deployments
2. **Standardize on Vue3 + TypeScript** following RAMP4 patterns  
3. **Use CKAN extensions pattern** for data-heavy applications
4. **Implement PowerShell + Power Platform** for workflow automation

#### Integration Opportunities:
1. **Cross-department APIs**: Many tools could share common data
2. **Unified authentication**: Leverage existing GC identity systems
3. **Shared components**: Extract common UI patterns into reusable libraries
4. **Data pipelines**: Connect Sarracenia, OpenTabulate, and LODE for data flow

### Security & Compliance
1. **Good practices**: Most repositories follow security standards
2. **MIT licensing preferred**: Enables easy reuse across departments
3. **Access controls**: Proper use of GitHub organizations and permissions
4. **Documentation**: Security practices well-documented where needed

### Innovation Indicators
1. **AI/ML Adoption**: Growing use in CSE (Assemblyline) and DND research
2. **Cloud-Native**: StatCan leading with Kubernetes and microservices
3. **Modern Frontend**: Vue3 adoption shows commitment to current technology
4. **Data Integration**: LODE project shows advanced data linking capabilities

---

## Conclusion

The Government of Canada's open source ecosystem demonstrates strong technical capabilities with clear opportunities for integration across HICC, ACCORD, and CDR systems. The foundation exists for building sophisticated, interconnected systems leveraging proven patterns and technologies already in production across multiple departments.

**Key Success Factors:**
- Leverage StatCan's advanced analytics and Kubernetes expertise
- Build on TBS's template and standards work
- Integrate CDS's user experience and digital service patterns
- Utilize existing data processing pipelines and compliance frameworks

**Next Steps:**
1. Deploy this audit to the CDR repository
2. Initiate cross-department collaboration discussions
3. Begin pilot integration projects
4. Establish shared technical standards and governance

---
*Report compiled by CDR analysis system*  
*Source repositories: 500+ across 9+ GC organizations*  
*Analysis date: March 16, 2026*