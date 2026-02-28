# AI Agents, Tools & Resources for the OpenJuice Project

> **Last updated:** 2026-02-27
>
> Research into AI agents, tools, and community resources that can assist with porting
> OpenEVSE firmware (ATmega328P, C/C++) to JuiceBox Gen 1 EVSE hardware. Covers coding
> agents, code review tools, embedded-specific AI, open-source/self-hosted options, and
> community resources.

---

## Table of Contents

1. [AI Coding Agents](#1-ai-coding-agents)
2. [AI-Powered Code Review Tools](#2-ai-powered-code-review-tools)
3. [Specialized Embedded / Hardware AI Tools](#3-specialized-embedded--hardware-ai-tools)
4. [Open-Source / Self-Hosted AI Agents](#4-open-source--self-hosted-ai-agents)
5. [Community Resources](#5-community-resources)
6. [Summary Matrix](#6-summary-matrix)
7. [Recommendations](#7-recommendations)

---

## 1. AI Coding Agents

### 1.1 Claude Code (Anthropic) -- CURRENTLY IN USE

- **URL:** <https://claude.com/product/claude-code>
- **Cost:** Pro $20/mo (~45 messages/5hr), Max $100/mo (5x) or $200/mo (20x); API usage also available
- **Embedded C / AVR support:** General-purpose but strong with C/C++. No MCU-specific tooling, but excellent at register-level code, bitwise operations, and datasheet interpretation when given context.

**How it helps OpenJuice:**

- Already the primary development tool for this project. Runs in the terminal alongside PlatformIO CLI.
- Can hold large context (up to 1M tokens in beta with Opus 4.6), allowing the entire OpenEVSE codebase plus JuiceBox pin mappings and datasheets to be loaded simultaneously.
- Excellent at multi-file refactoring (e.g., replacing `digitalRead()`/`digitalWrite()` with direct port manipulation).
- Can generate hardware abstraction layers, calculate voltage divider ratios, and derive ADC threshold values.
- Subagent patterns exist for embedded systems specialization (see [awesome-claude-code-subagents](https://github.com/VoltAgent/awesome-claude-code-subagents/blob/main/categories/07-specialized-domains/embedded-systems.md)).
- Supports spawning parallel agents in isolated Git worktrees for tackling multiple subsystems (pilot signal, GFI, relay control) concurrently.

**Limitations:** No direct hardware simulation or compilation; relies on PlatformIO in the terminal for build verification. No AVR-specific register autocompletion.

---

### 1.2 GitHub Copilot

- **URL:** <https://github.com/features/copilot>
- **Cost:** $10/mo individual, $19/mo business, $39/mo enterprise
- **Embedded C / AVR support:** General C/C++ support. No MCU-specific features.

**How it helps OpenJuice:**

- Real-time autocomplete in VS Code alongside the PlatformIO extension -- useful for boilerplate register configuration code.
- Can suggest AVR register names and bit masks if it has seen similar patterns in training data (Arduino/AVR codebases are well-represented).
- Copilot Chat can explain existing OpenEVSE code and suggest modifications.
- Integrates natively with GitHub, useful for PR descriptions and documentation.

**Limitations:** Autocomplete-focused; less capable for large-scale refactoring compared to agentic tools. Cannot execute commands or verify builds. Context window is smaller than Claude Code.

---

### 1.3 Cursor

- **URL:** <https://cursor.com>
- **Cost:** Free tier (limited), Pro $20/mo
- **Embedded C / AVR support:** General C/C++ via VS Code foundation. Supports PlatformIO extension.

**How it helps OpenJuice:**

- AI-native IDE (VS Code fork) with inline code generation and chat.
- "Composer" mode enables multi-file edits -- useful for coordinated pin remapping across header files and source files.
- Can reference project files as context when asking about pin mappings or register configurations.
- Supports multiple AI models (Claude, GPT-4o, etc.).

**Limitations:** IDE-based, which means less terminal integration than Claude Code. No embedded-specific intelligence.

---

### 1.4 Windsurf (Codeium)

- **URL:** <https://windsurf.com>
- **Cost:** Free tier, Pro ~$15/mo
- **Embedded C / AVR support:** General C/C++ support.

**How it helps OpenJuice:**

- "Cascade" agentic mode provides deep reasoning for architectural planning -- useful for designing the hardware abstraction layer between OpenEVSE and JuiceBox.
- Good at understanding codebases holistically before making changes.
- Can work across multiple files simultaneously.

**Limitations:** Cloud-based AI processing; less suitable if code privacy is a concern. No embedded-specific features.

---

### 1.5 Kiro (AWS)

- **URL:** <https://kiro.dev>
- **Cost:** Free tier available; paid tiers for advanced features
- **Embedded C / AVR support:** Supports C and C++ among many languages. No MCU-specific features.

**How it helps OpenJuice:**

- Spec-driven development: generates requirements documents, design specifications, and implementation task lists before writing code. Could be useful for formally specifying the pin mapping and hardware abstraction requirements.
- Based on VS Code (Code OSS), so it supports PlatformIO extension.
- Powered by Claude Sonnet, so reasoning quality is high.

**Limitations:** Primarily oriented toward AWS cloud development workflows. Embedded/MCU development is not a focus area.

---

## 2. AI-Powered Code Review Tools

### 2.1 Qodo (formerly Codium)

- **URL:** <https://www.qodo.ai>
- **Cost:** Free for individuals; Teams $19/user/mo
- **Embedded C / AVR support:** General C/C++ support. No embedded-specific rules.

**How it helps OpenJuice:**

- Automated PR review with agentic code suggestions -- catches logic errors, security issues, and style violations.
- Test generation for code changes -- could generate unit tests for ADC conversion functions, pilot signal timing, etc.
- Custom rules enforcement -- could encode JuiceBox-specific safety constraints (e.g., relay must not close without valid pilot signal).
- Multi-repo indexing -- can understand both OpenEVSE upstream and OpenJuice fork simultaneously.
- Qodo 2.0 (Feb 2026) introduced multi-agent review architecture with highest recall among tested tools.

**Limitations:** No MISRA/embedded-specific rule sets. Not a substitute for formal static analysis.

---

### 2.2 Parasoft C/C++test

- **URL:** <https://www.parasoft.com/products/parasoft-c-ctest/>
- **Cost:** Commercial license (contact for pricing; typically $2,000-5,000+/seat/year)
- **Embedded C / AVR support:** YES -- purpose-built for embedded C/C++. Full MISRA C:2023 and MISRA C:2025 support.

**How it helps OpenJuice:**

- AI-enhanced static analysis that explains violations in context and suggests compliant fixes.
- Full MISRA C compliance checking -- critical for EVSE safety code (relay control, GFI detection, overcurrent protection).
- Certified by TUV SUD for ISO 26262 and IEC 61508 compliance.
- Can detect memory safety issues, undefined behavior, and race conditions in interrupt handlers.
- AI assistant for rapid access to documentation and rule explanations.

**Limitations:** Expensive for a hobby/open-source project. May be overkill for ATmega328P firmware, but the safety analysis is genuinely valuable for an EV charger.

---

### 2.3 PC-lint Plus

- **URL:** <https://pclintplus.com>
- **Cost:** Commercial license (approximately $400-1,000 per seat)
- **Embedded C / AVR support:** YES -- supports AVR/GCC toolchains. MISRA C:2012, C:2023, and C:2025 checking.

**How it helps OpenJuice:**

- Lightweight, fast static analysis that integrates into PlatformIO build workflows.
- Detects bugs at the register manipulation level -- catches incorrect bit shifts, wrong register accesses, type mismatches in port operations.
- MISRA compliance checking for safety-critical EVSE code paths.
- Command-line tool that fits naturally into CI/CD pipelines.
- Supports GCC compiler configurations used by PlatformIO's AVR toolchain.

**Limitations:** Not AI-powered (rule-based), but highly effective for the kinds of bugs common in embedded pin remapping work. More affordable than Parasoft.

---

### 2.4 Arm AI-Enabled Security Code Review (Metis)

- **URL:** <https://developer.arm.com/community/arm-community-blogs/b/ai-blog/posts/empowering-engineers-with-ai-enabled-security-code-review>
- **Cost:** Research/internal tool (check Arm for availability)
- **Embedded C / AVR support:** Designed for embedded systems, but primarily ARM-focused.

**How it helps OpenJuice:**

- Uses AI to go beyond rule-based detection, understanding what the system is *meant* to do.
- Builds a knowledge base from actual code and documentation to identify semantic security issues.
- Complements traditional static analysis tools.

**Limitations:** ARM-focused, not AVR. May not be publicly available as a standalone product. Included here for awareness.

---

## 3. Specialized Embedded / Hardware AI Tools

### 3.1 Embedder -- HIGHEST RELEVANCE

- **URL:** <https://embedder.com>
- **Cost:** $20/mo unlimited (all AI models, unlimited uploads and code generation)
- **Embedded C / AVR support:** YES -- explicitly supports AVR among 300+ MCU variants. Also ESP32, STM32, nRF52, NXP, RP2040, RISC-V.

**How it helps OpenJuice:**

- **Purpose-built for exactly this kind of work.** Parses actual PDF datasheets, timing diagrams, schematics, and block diagrams -- does not hallucinate register addresses.
- Finds register definitions in reference manuals, timing requirements in datasheets, and known silicon bugs in errata documents.
- Can generate peripheral driver code (GPIO, ADC, PWM, UART, timers) with MISRA C:2012 compliance.
- Extracts pin mappings from schematics -- directly applicable to mapping JuiceBox hardware pins to OpenEVSE firmware expectations.
- Dual-layer verification: Software-in-the-Loop (SIL) testing with custom simulators plus Hardware-in-the-Loop (HIL) validation.
- TUI (terminal UI) interface with LSP server integration providing real-time compilation diagnostics for C/C++.
- Used by engineers at Tesla, NVIDIA, Medtronic for safety-critical firmware.
- YC S25 company, actively maintained.

**This is the single most relevant specialized tool for the OpenJuice project.**

---

### 3.2 Microchip MPLAB AI Coding Assistant

- **URL:** <https://www.microchip.com/en-us/tools-resources/develop/mplab-tools-vs-code/mplab-ai-coding-assistant>
- **Cost:** Free (some advanced features may require subscription)
- **Embedded C / AVR support:** YES -- Microchip owns AVR (acquired Atmel). Supports PIC and AVR families.

**How it helps OpenJuice:**

- **Built by the chip vendor.** References Microchip's own vectorized datasheets for code generation.
- Can interpret high-level commands like "Set up an ADC to sample every second and output to UART" and generate fully functional C-based initialization code with correct register values for the specific MCU.
- In-line error detection that scans for incorrect register values and misconfigured peripheral settings -- exactly what's needed when remapping pins.
- Based on Continue (open-source), so it's a VS Code extension that works alongside PlatformIO.
- Provides block diagrams directly in VS Code.
- Supports AVR development through MCC Melody tooling.

**Highly relevant because ATmega328P is a Microchip/Atmel part and the AI has been trained on Microchip's own datasheets.**

---

### 3.3 ETAS Embedded AI Coder

- **URL:** <https://www.etas.com/ww/en/products-services/software-development-tools/embedded-ai-coder/>
- **Cost:** Commercial (contact ETAS)
- **Embedded C / AVR support:** Automotive-focused embedded C. Primarily targets 32-bit MCUs.

**How it helps OpenJuice:**

- Complies with ISO 26262 and MISRA standards.
- Generates numerically correct, runtime-error-free code.
- Relevant if the project ever moves to automotive-grade safety certification.

**Limitations:** Designed for converting neural network models to embedded C, not general firmware porting. Less relevant for this project's immediate needs but worth knowing about.

---

## 4. Open-Source / Self-Hosted AI Agents

### 4.1 Aider

- **URL:** <https://aider.chat>
- **Source:** <https://github.com/Aider-AI/aider>
- **Cost:** Free and open-source (Apache 2.0). Pay only for LLM API calls.
- **Embedded C / AVR support:** General C/C++ via any connected LLM. Supports 100+ languages.

**How it helps OpenJuice:**

- Terminal-based AI pair programming that treats Git as a first-class citizen -- automatically stages and commits changes with descriptive messages.
- Maps the entire codebase to provide broad context to the LLM, important for understanding OpenEVSE's interconnected modules.
- Can connect to Claude, GPT-4o, DeepSeek, or local models via Ollama for fully offline operation.
- Architect mode for planning + Editor mode for implementation -- useful for designing the abstraction layer first, then implementing it.
- Very low cost with DeepSeek or local models ($0.01-0.10 per feature implementation).

**Limitations:** No embedded-specific features. Relies entirely on the connected LLM's knowledge. No compilation or hardware verification.

---

### 4.2 Cline

- **URL:** <https://cline.bot>
- **Source:** <https://github.com/cline/cline> (Apache 2.0)
- **Cost:** Free and open-source. Pay only for LLM API calls.
- **Embedded C / AVR support:** General C/C++ support through any connected LLM.

**How it helps OpenJuice:**

- VS Code extension with full terminal access -- can run PlatformIO builds, upload firmware, and see compilation errors directly.
- Plan mode (thinking) + Act mode (doing) with human-in-the-loop approval at each step -- important for safety-critical firmware changes.
- Can read files, create/edit across multiple files, execute terminal commands, and interact with the browser.
- Connects to Claude, GPT, Gemini, Bedrock, or local models via Ollama/LM Studio.
- 5M+ developers, very active community.

**Limitations:** Token usage can be high with large codebases. No embedded-specific intelligence.

---

### 4.3 Roo Code

- **URL:** <https://roocode.com>
- **Source:** <https://github.com/RooCodeInc/Roo-Code> (open-source)
- **Cost:** Free and open-source. Pay only for LLM API calls.
- **Embedded C / AVR support:** General C/C++ support.

**How it helps OpenJuice:**

- Specialized modes: Architect, Code, Debug, Ask, and Custom -- each activates different VS Code tool subsets.
- Multi-file editing with holistic codebase understanding.
- Local execution model -- all code intelligence stays on your machine, no data leaves.
- Model-agnostic: works with any LLM provider or local models.
- Could define a custom "Embedded" mode with project-specific rules and context.

**Limitations:** No embedded-specific features out of the box.

---

### 4.4 Continue.dev

- **URL:** <https://www.continue.dev>
- **Source:** <https://github.com/continuedev/continue> (open-source)
- **Cost:** Free and open-source.
- **Embedded C / AVR support:** General C/C++. Foundation for Microchip's MPLAB AI Coding Assistant (see 3.2).

**How it helps OpenJuice:**

- Open-source VS Code/JetBrains extension with agent, chat, edit, and autocomplete modes.
- Fully air-gappable with local LLMs via Ollama -- no internet connection required.
- Highly customizable: can add custom context providers, slash commands, and model configurations.
- Could be configured with ATmega328P datasheet content as a custom context provider.
- Since MPLAB AI Coding Assistant is built on Continue, the customization patterns are proven for embedded work.

**Limitations:** Requires manual configuration for embedded-specific context. No built-in MCU knowledge.

---

### 4.5 OpenHands (formerly OpenDevin)

- **URL:** <https://openhands.dev>
- **Source:** <https://github.com/OpenHands/OpenHands>
- **Cost:** Free open-source (local), cloud version available, enterprise self-hosted via Kubernetes.
- **Embedded C / AVR support:** General-purpose coding agent.

**How it helps OpenJuice:**

- Full software engineering agent that can modify code, run terminal commands, browse the web, and write documentation.
- Python SDK for defining custom agents -- could create an embedded firmware porting agent with project-specific knowledge.
- Sandboxed Docker runtimes for safe command execution.
- Model-agnostic: works with any LLM backend.
- Could be configured as a CI agent to automatically test firmware builds.

**Limitations:** Cloud/container-oriented architecture. More complex setup than terminal-based tools. No embedded-specific features.

---

### 4.6 OpenCode

- **URL:** <https://opencode.ai>
- **Source:** Open-source
- **Cost:** Free and open-source.
- **Embedded C / AVR support:** General-purpose.

**How it helps OpenJuice:**

- Terminal-based AI coding agent, similar to Claude Code but open-source.
- Can be used with any LLM backend.
- Lightweight alternative for terminal-centric embedded development workflows.

**Limitations:** Newer project, smaller community. No embedded-specific features.

---

## 5. Community Resources

### 5.1 OpenEVSE Communities

| Resource | URL | Relevance |
|---|---|---|
| OpenEVSE GitHub | <https://github.com/openevse> | Source code for all OpenEVSE firmware, hardware designs, and ESP32 WiFi module |
| OpenEVSE Forums | <https://openev.freshdesk.com/support/discussions> | Official support discussions, build guides, troubleshooting |
| OpenEnergyMonitor Forum (OpenEVSE section) | <https://community.openenergymonitor.org/c/integrations/openevse/43> | Active development community, energy monitoring integration, smart charging |
| OpenEVSE Build Guides (Dozuki) | <https://openevse.dozuki.com> | Step-by-step hardware assembly and configuration guides |
| Hackaday - OpenEVSE tag | <https://hackaday.com/tag/openevse/> | Project coverage, community discussion, related EVSE projects |

### 5.2 JuiceBox EVSE Resources

| Resource | URL | Relevance |
|---|---|---|
| JuiceBox Original Firmware (valerun) | <https://github.com/valerun/JuiceBox_EVSE_firmware> | Reference firmware for JuiceBox Gen 1 hardware, pin mappings, peripheral configuration |
| JuiceBox Firmware V8.9 (valerun) | <https://github.com/valerun/JB_firmware_V8_9> | Later firmware version with additional features |
| JuiceBox Firmware (dcarter fork) | <https://github.com/dcarter/JuiceBox_EVSE_Firmware> | Community fork based on v8.9.3 sources |
| JuiceBox Firmware (enachb) | <https://github.com/enachb/juicebox-ev-charger-8.7.9> | Another community archive of JuiceBox firmware |
| OpenEVSE Forum - JuiceBox Repurposing | <https://openev.freshdesk.com/support/discussions/topics/6000069506> | Discussion of hacking OpenEVSE onto JuiceBox hardware |
| MyRav4EV Forum - JuiceBox Firmware Modification | <https://www.myrav4ev.com/threads/how-to-modify-juicebox-firmware.1278/> | Community thread on modifying JuiceBox firmware |

### 5.3 AVR Development Communities

| Resource | URL | Relevance |
|---|---|---|
| AVR Freaks | <https://www.avrfreaks.net> | Premier community for 8-bit and 32-bit AVR development. ATmega328P discussions, register-level help, debugging techniques. |
| Arduino Forums | <https://forum.arduino.cc> | ATmega328P is the Arduino Uno's MCU. Massive library of examples, tutorials, and community support for the same chip. |
| PlatformIO Community | <https://community.platformio.org> | Build system community. Help with `platformio.ini` configuration, AVR toolchain issues, library management. |
| r/embedded (Reddit) | <https://www.reddit.com/r/embedded/> | General embedded development discussions, AVR topics, firmware porting experiences. |
| r/arduino (Reddit) | <https://www.reddit.com/r/arduino/> | ATmega328P-specific help, register-level programming, hardware interfacing. |
| Hackaday.io | <https://hackaday.io> | Project hosting and community for hardware hacking projects. Multiple EVSE and EV charging projects. |

### 5.4 EV Charging / Hacking Communities

| Resource | URL | Relevance |
|---|---|---|
| Speak EV Forums | <https://www.speakev.com> | UK-based EV forum with DIY charger discussions |
| DIY Solar Power Forum | <https://diysolarforum.com> | Solar-integrated EV charging, EVSE hacking discussions |
| Pwn2Own Automotive Research | <https://sector7.computest.nl/post/2024-08-pwn2own-automotive-juicebox-40/> | Security research on JuiceBox 40 -- contains detailed hardware/firmware analysis |

---

## 6. Summary Matrix

| Tool | Type | Cost | Embedded C | AVR Specific | OpenJuice Relevance |
|---|---|---|---|---|---|
| **Claude Code** | Coding Agent | $20-200/mo | Yes (general) | No | **HIGH** -- currently in use |
| **Embedder** | Firmware AI | $20/mo | **YES** | **YES (300+ MCUs)** | **HIGHEST** -- purpose-built |
| **MPLAB AI Assistant** | Vendor AI | Free | **YES** | **YES (Microchip/AVR)** | **HIGH** -- chip vendor's own tool |
| **GitHub Copilot** | Autocomplete | $10-39/mo | Yes (general) | No | Medium -- good for boilerplate |
| **Cursor** | AI IDE | $0-20/mo | Yes (general) | No | Medium -- multi-file editing |
| **Windsurf** | AI IDE | $0-15/mo | Yes (general) | No | Medium -- architectural planning |
| **Kiro** | AI IDE | Free+ | Yes (general) | No | Low-Medium -- spec-driven dev |
| **Aider** | OSS Agent | Free + API | Yes (general) | No | Medium -- terminal + Git native |
| **Cline** | OSS Agent | Free + API | Yes (general) | No | Medium -- VS Code + terminal |
| **Roo Code** | OSS Agent | Free + API | Yes (general) | No | Medium -- custom modes |
| **Continue.dev** | OSS Agent | Free + API | Yes (general) | No | Medium -- foundation for MPLAB AI |
| **OpenHands** | OSS Agent | Free | Yes (general) | No | Low-Medium -- complex setup |
| **Parasoft C/C++test** | Static Analysis | $$$ (commercial) | **YES** | **YES** | Medium -- safety analysis |
| **PC-lint Plus** | Static Analysis | $400-1000 | **YES** | **YES (GCC/AVR)** | Medium -- affordable MISRA |
| **Qodo** | Code Review | Free-$19/mo | Yes (general) | No | Low-Medium -- PR review |

---

## 7. Recommendations

### Immediate Additions to the Workflow

1. **Embedder ($20/mo)** -- The single most impactful addition. It understands AVR registers, can parse the ATmega328P datasheet, and generates hardware-correct peripheral code. Use it alongside Claude Code: let Claude Code handle the high-level porting logic and multi-file refactoring, and use Embedder for register-level code generation and datasheet verification.

2. **Microchip MPLAB AI Coding Assistant (Free)** -- Install this VS Code extension immediately. It has been trained on Microchip's own ATmega328P datasheets and can generate correct ADC, PWM, and GPIO initialization code with proper register values. Since the ATmega328P is a Microchip part, this tool has authoritative knowledge of the chip.

### Recommended Workflow Stack

```
Primary Agent:        Claude Code (high-level porting, refactoring, architecture)
Register Verification: Embedder (datasheet-aware code generation, pin mapping)
Vendor AI:            MPLAB AI Coding Assistant (ATmega328P-specific register code)
Autocomplete:         GitHub Copilot or Continue.dev (in VS Code alongside PlatformIO)
Code Review:          Qodo (automated PR review) + PC-lint Plus (MISRA/static analysis)
Build System:         PlatformIO CLI (integrated with all above tools)
```

### For Safety-Critical Code Paths

The relay control, GFI detection, and overcurrent protection code paths in the EVSE firmware are safety-critical. For these sections specifically:

- Run PC-lint Plus with MISRA C:2012 checking enabled on every build.
- Use Parasoft C/C++test if budget allows, especially for the interrupt handlers and timing-critical pilot signal generation.
- Have Claude Code and Embedder cross-check each other's output for register-level operations.
- Treat all AI-generated firmware as draft material requiring full code review, static analysis, and hardware validation on the actual JuiceBox hardware with ISP programmer.

### For Budget-Conscious Development

If minimizing cost:

```
Free:    MPLAB AI Coding Assistant + Continue.dev + Aider (with DeepSeek API)
$20/mo:  Add Embedder for datasheet-aware register code
$40/mo:  Add Claude Code Pro for high-quality agentic development
```

---

*This document should be periodically updated as the AI tooling landscape for embedded development evolves rapidly. Tools like Embedder and MPLAB AI Coding Assistant are particularly worth monitoring for new AVR-specific features.*
