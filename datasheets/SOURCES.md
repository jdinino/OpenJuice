# OpenJuice Project - Datasheet and Documentation Sources

Reference URLs for all key components and related projects used in the OpenJuice project
(porting OpenEVSE firmware to JuiceBox Gen 1 EVSE hardware).

Last updated: 2026-02-27

---

## 1. ATmega328P - Microchip AVR Microcontroller

| # | Name | URL | Description | Free |
|---|------|-----|-------------|------|
| 1a | ATmega328P Datasheet (Official Microchip PDF) | https://ww1.microchip.com/downloads/en/DeviceDoc/Atmel-7810-Automotive-Microcontrollers-ATmega328P_Datasheet.pdf | Complete official datasheet for the ATmega328P 8-bit AVR microcontroller (automotive variant, same die) | Yes |
| 1b | ATmega328P Product Page (Microchip) | https://www.microchip.com/en-us/product/atmega328p | Microchip product page with links to all documentation, errata, and application notes | Yes |
| 1c | ATmega48A/PA/88A/PA/168A/PA/328/P Datasheet (Complete Family) | https://ww1.microchip.com/downloads/en/DeviceDoc/ATmega48A-PA-88A-PA-168A-PA-328-P-DS-DS40002061A.pdf | Combined datasheet covering the full ATmega48/88/168/328 family with all register details | Yes |

---

## 2. AMW006 - Zentri / ACKme / Silicon Labs WiFi Module

| # | Name | URL | Description | Free |
|---|------|-----|-------------|------|
| 2a | AMW006-A1x Datasheet (Hardware) | https://www.silabs.com/documents/public/data-sheets/ADS-AMW006-A1x-101R.pdf | Hardware datasheet for the AMW006 "Numbat" WiFi module (pinout, electrical specs, dimensions) | Yes |
| 2b | Zentri AMW006 / AMW106 Data Sheet (ZentriOS) | https://www.silabs.com/documents/public/data-sheets/ADS-MWx06-ZentriOS.pdf | Combined datasheet covering AMW006 and AMW106 modules running ZentriOS firmware | Yes |
| 2c | AMW006 Product Page (Silicon Labs) | https://www.silabs.com/wireless/wi-fi/zentri-legacy-modules/device.amw006 | Silicon Labs product page for the AMW006 legacy Zentri WiFi module | Yes |

---

## 3. JuiceBox Gen 1 EVSE - Hardware Documentation

### 3a. FCC Filings

| # | Name | URL | Description | Free |
|---|------|-----|-------------|------|
| 3a1 | FCC ID 2A4LRJB201NA - JuiceBox Pro User Manual | https://fcc.report/FCC-ID/2A4LRJB201NA/5820432.pdf | FCC filing for JuiceBox Pro (FCC grantee 2A4LR = eMotorWerks/Enel X), includes user manual | Yes |
| 3a2 | FCC ID Search Tool | https://apps.fcc.gov/oetcf/eas/reports/GenericSearch.cfm | Search for additional JuiceBox FCC filings using grantee code "2A4LR" | Yes |
| 3a3 | FCC ID Lookup (fcc.report) | https://fcc.report/FCC-ID/2A4LRJB201NA | Community-friendly mirror of FCC filings for JuiceBox with all documents indexed | Yes |

### 3b. Repair and Teardown Resources

| # | Name | URL | Description | Free |
|---|------|-----|-------------|------|
| 3b1 | JuiceBox - Repair Wiki | https://repair.wiki/w/JuiceBox | Community wiki documenting board versions 8.6-8.17.9, component identification, and repair info | Yes |
| 3b2 | JuiceBox EVSE - iFixit | https://www.ifixit.com/Device/JuiceBox_EVSE | iFixit device page with teardown photos, repair guides, and beep code documentation | Yes |
| 3b3 | JuiceBox EVSE Relay Replacement Guide | https://www.ifixit.com/Guide/JuiceBox+EVSE+Relay+Replacement+(Old+style)/139619 | Step-by-step relay replacement with internal photos (old-style boards) | Yes |
| 3b4 | JuiceBox Beep Codes | https://www.ifixit.com/Guide/Beep+codes+for+JuiceBox+EVSE/139550 | Beep code reference for diagnosing JuiceBox hardware faults | Yes |

### 3c. Original JuiceBox Firmware (Open Source)

| # | Name | URL | Description | Free |
|---|------|-----|-------------|------|
| 3c1 | valerun/JuiceBox_EVSE_firmware | https://github.com/valerun/JuiceBox_EVSE_firmware | Original JuiceBox firmware by Val Miftakhov (eMotorWerks founder), Arduino/ATmega328P | Yes |
| 3c2 | valerun/JB_firmware_V8_9 | https://github.com/valerun/JB_firmware_V8_9 | JuiceBox firmware version 8.9 for 60A EVSE variant | Yes |
| 3c3 | dcarter/JuiceBox_EVSE_Firmware | https://github.com/dcarter/JuiceBox_EVSE_Firmware | Community fork based on 8.9.3 sources with improvements and documentation | Yes |
| 3c4 | enachb/juicebox-ev-charger-8.7.9 | https://github.com/enachb/juicebox-ev-charger-8.7.9 | Archived copy of JuiceBox firmware version 8.7.9 | Yes |
| 3c5 | valerun/JuiceBox_EVSE_WiFi_programmer_Public | https://github.com/valerun/JuiceBox_EVSE_WiFi_programmer_Public | WiFi module programmer utility for JuiceBox AMW006 module | Yes |

### 3d. JuiceBox Spec Sheets

| # | Name | URL | Description | Free |
|---|------|-----|-------------|------|
| 3d1 | JuiceBox Pro 40 Spec Sheet | https://greenridgesolar.com/wp-content/uploads/2023/12/JuiceBox_Pro-40-specs_8-6-18.pdf | Official eMotorWerks JuiceBox Pro 40 specifications (2018) | Yes |
| 3d2 | Enel X JuiceBox Pro User Manual (ManualsLib) | https://www.manualslib.com/manual/2592169/Enel-X-Juicebox-Pro.html | Enel X branded JuiceBox Pro user manual, online viewer | Yes |

---

## 4. OpenEVSE Hardware and Firmware

### 4a. Hardware Schematics

| # | Name | URL | Description | Free |
|---|------|-----|-------------|------|
| 4a1 | OpenEVSE/OpenEVSE_PLUS (Hardware) | https://github.com/OpenEVSE/OpenEVSE_PLUS | Main OpenEVSE hardware repo with Eagle SCH/BRD files (CC BY-SA 3.0), current version v6.5.1 | Yes |
| 4a2 | Everters EasyEDA OpenEVSE Schematics | https://github.com/everters/Everters_OpenEVSE | EasyEDA version of OpenEVSE schematics ready for JLCPCB production with LCSC components | Yes |
| 4a3 | OpenEVSE Organization (GitHub) | https://github.com/openevse | GitHub organization page listing all OpenEVSE repositories | Yes |

### 4b. Firmware

| # | Name | URL | Description | Free |
|---|------|-----|-------------|------|
| 4b1 | OpenEVSE/open_evse (ATmega328P Firmware) | https://github.com/OpenEVSE/open_evse | Main OpenEVSE AVR firmware for ATmega328P (GPLv3), includes PlatformIO build config | Yes |
| 4b2 | lincomatic/open_evse (Development Branch) | https://github.com/lincomatic/open_evse | Development branch of OpenEVSE firmware with latest features | Yes |
| 4b3 | OpenEVSE Firmware Loading Guide | https://github.com/OpenEVSE/open_evse/blob/master/firmware/open_evse/LoadingFirmware.md | Instructions for flashing firmware via USBasp: `avrdude -p atmega328p -c usbasp -e -U flash:w:firmware.hex` | Yes |
| 4b4 | OpenEVSE ESP32 WiFi Firmware | https://github.com/OpenEVSE/ESP32_WiFi_V4.x | ESP32-based WiFi module firmware (supports MQTT, HTTP, OCPP 1.6J) | Yes |

### 4c. Documentation and Guides

| # | Name | URL | Description | Free |
|---|------|-----|-------------|------|
| 4c1 | OpenEVSE SAE J1772 Theory of Operation | https://openev.freshdesk.com/support/solutions/articles/6000052070-theory-of-operation | Detailed explanation of how OpenEVSE implements J1772 pilot signal generation and sensing | Yes |
| 4c2 | Basics of SAE J1772 (OpenEVSE) | https://openev.freshdesk.com/support/solutions/articles/6000052074-basics-of-sae-j1772 | Beginner-friendly overview of SAE J1772 signaling as implemented in OpenEVSE | Yes |
| 4c3 | OpenEVSE Dozuki Guides | https://openevse.dozuki.com/Guide/OpenEVSE+P50D-WV+kit++alternate+build+guide/25 | Step-by-step hardware build and assembly guides with photos | Yes |

---

## 5. SAE J1772 Pilot Signal - Technical References

| # | Name | URL | Description | Free |
|---|------|-----|-------------|------|
| 5a | SAE J1772 - Wikipedia | https://en.wikipedia.org/wiki/SAE_J1772 | Comprehensive summary of J1772 connector, pilot signal states, PWM duty cycle encoding, and voltage levels | Yes |
| 5b | OpenEVSE J1772 Technical Reference (PDF) | https://www.fveaa.org/fb/J1772_386.pdf | Detailed J1772 technical reference from the Fox Valley Electric Auto Association | Yes |
| 5c | J1772 Research - Robert Crimmins | https://robertcrimmins.com/J1772.html | Independent technical deep-dive into J1772 pilot signal timing, states A-F, and circuit design | Yes |
| 5d | Understanding SAE J1772 (InfiniPower) | https://www.infinipowertech.com/understanding-sae-j1772-technical-insights-for-charger-testing/ | Technical insights for charger testing: pilot signal waveforms, voltage thresholds, state transitions | Yes |
| 5e | Proximity Pilot and Control Pilot Overview | https://philipmcgaw.com/proximity-pilot-and-control-pilot-overview/ | Clear diagrams of CP/PP circuits, resistor values for each vehicle state | Yes |
| 5f | J1772 Plug Pinout and Signaling (RF Wireless World) | https://www.rfwireless-world.com/Terminology/SAE-J1772-Plug-Pin-diagram-and-J1772-Signaling-circuit.html | Pin diagram and signaling circuit schematic for J1772 connector | Yes |
| 5g | Minimalist EVSE Charger Circuits | https://philipmcgaw.com/minimalist-evse-charger-circuits/ | Simplified EVSE circuit designs showing op-amp pilot generation and relay control | Yes |

---

## 6. USBasp ISP Programmer

| # | Name | URL | Description | Free |
|---|------|-----|-------------|------|
| 6a | USBasp Official Page (fischl.de) | https://www.fischl.de/usbasp/ | Original USBasp project page by Thomas Fischl with schematics, firmware, and pinout | Yes |
| 6b | USBASP Pinout Reference | https://www.datasheetcafe.com/usbasp-pinout-avr-programmer/ | Clear pinout diagrams for both 6-pin and 10-pin ISP headers | Yes |
| 6c | USBasp 10-Pin Programming Guide | http://www.learningaboutelectronics.com/Articles/Program-AVR-chip-using-a-USBASP-with-10-pin-cable.php | Step-by-step wiring guide from USBasp 10-pin header to ATmega328P target | Yes |

### USBasp ISP Pinout Quick Reference (6-pin)

```
Pin 1: MISO     Pin 2: VCC (+5V)
Pin 3: SCK      Pin 4: MOSI
Pin 5: RESET    Pin 6: GND
```

---

## 7. JuiceRescueController and Juice Rescue Community

### 7a. JuiceRescueController Project

| # | Name | URL | Description | Free |
|---|------|-----|-------------|------|
| 7a1 | OpenEVSE/JuiceRescueController (GitHub) | https://github.com/OpenEVSE/JuiceRescueController | OpenEVSE-based EVSE and WiFi controller replacement board for JuiceBox v1 and v2 (Eagle files) | Yes |
| 7a2 | JuiceRescueController README | https://github.com/OpenEVSE/JuiceRescueController/blob/main/README.md | Documentation for the replacement controller board including BOM and installation notes | Yes |
| 7a3 | Replace Controller in JuiceBox v1 (Dozuki Guide) | https://openevse.dozuki.com/Guide/Replace+Controller+in+Juicebox+v1/52 | Step-by-step guide with photos for replacing the controller in metal-case JuiceBox v1 | Yes |
| 7a4 | Replace Controller in JuiceBox v2 (Dozuki Guide) | https://openevse.dozuki.com/Guide/Replace+Controller+in+Juicebox+v2/53 | Step-by-step guide with photos for replacing the controller in plastic-case JuiceBox v2 | Yes |
| 7a5 | OpenEVSE Store - Replacement for JuiceBox v1 | https://store.openevse.com/products/replacement-electronics-for-juicebox-v1-metal-black-and-orange | Purchasable replacement electronics kit for JuiceBox v1 (metal, black/grey and orange) | Yes |
| 7a6 | OpenEVSE Store - Replacement for JuiceBox v2 | https://store.openevse.com/products/replacement-electronics-for-juicebox-v2-plastic-grey-and-white | Purchasable replacement electronics kit for JuiceBox v2 (plastic, purple/grey and white) | Yes |

### 7b. Juice Rescue Community

| # | Name | URL | Description | Free |
|---|------|-----|-------------|------|
| 7b1 | Juice Rescue Website | https://juice-rescue.org/ | Main community website organizing efforts to save JuiceBox chargers after Enel X shutdown | Yes |
| 7b2 | JuiceRescue GitHub Organization | https://github.com/JuiceRescue | GitHub org with community tools including juice-rescue.org website source and utilities | Yes |
| 7b3 | Juice Rescue Survey and Review (Jan 2025) | https://juice-rescue.org/2025-01-juice-rescue-review-and-survey | Community survey results and project status overview | Yes |
| 7b4 | Juice Rescue FTC Letter | https://juice-rescue.org/documents/2024-10-10-Juicebox-letter-to-FTC.pdf | Letter sent to the FTC about Enel X's abandonment of JuiceBox customers | Yes |
| 7b5 | Reverse-Engineering the Enel X Way API | https://gist.github.com/tomayac/754284dd79e20147f482d932ed89f2a1 | GitHub Gist documenting reverse engineering of the Enel X Way cloud API | Yes |

### 7c. Blog Posts and Teardowns

| # | Name | URL | Description | Free |
|---|------|-----|-------------|------|
| 7c1 | JuiceBox and an OpenEVSE Control Board | https://codinginthetrenches.com/2025/08/08/juicebox-and-an-openevse-control-board/ | Blog post documenting swapping in an OpenEVSE board, comparing board layouts and components | Yes |
| 7c2 | Internet of Annoyance and The JuiceBox | https://codinginthetrenches.com/2025/07/30/internet-of-annoyance-and-the-juicebox/ | Blog post about the problems caused by Enel X shutdown and motivations for open-source replacement | Yes |
| 7c3 | EVSE Install: JuiceBox Pro 40 (Jay's Technical Talk) | https://www.summet.com/blog/2015/09/28/evse-install-juicebox-pro-40/ | Detailed installation blog post with photos of the JuiceBox Pro 40 internals | Yes |
| 7c4 | JuiceBox - Spare Electrons Blog | https://spareelectrons.wordpress.com/tag/juicebox/ | Technical blog posts tagged "juicebox" covering hacking and modifications | Yes |
| 7c5 | Escaping Tethered Products: Juice Rescue (J. Nathan Matias) | https://natematias.com/portfolio/2025-08-22-unchaining-from-broken-software-tethers/ | Academic/advocacy perspective on the Juice Rescue project and right-to-repair implications | Yes |
| 7c6 | We Make Our Juice Boxes Open Source (EVsoup) | https://www.evsoup.com/we-make-our-juice-boxes-open-source-thanks-to-open-evse/ | News article about the community effort to make JuiceBox chargers open source via OpenEVSE | Yes |

### 7d. Community Forum Discussions

| # | Name | URL | Description | Free |
|---|------|-----|-------------|------|
| 7d1 | eMotorWerks JuiceBox - Open Source 15kW EVSE (Rav4 EV Forum) | https://www.myrav4ev.com/threads/e-motorwerks-juicebox-an-open-source-15kw-evse.893/ | Early forum thread about the original open-source JuiceBox with technical details from the creator | Yes |
| 7d2 | eMotorWerks JuiceBox (Nissan Leaf Forum) | https://mynissanleaf.com/threads/e-motorwerks-juicebox-an-open-source-15kw-evse.15444/ | Community discussion thread with JuiceBox technical details and user experiences | Yes |
| 7d3 | Open Source EVSEs: OpenEVSE vs JuiceBox | https://mynissanleaf.com/threads/open-source-evses-openevse-vs-juicebox.13556/ | Comparison thread between OpenEVSE and JuiceBox hardware/firmware approaches | Yes |
| 7d4 | Retrofitting a JuiceBox (OpenEVSE Support) | https://openev.freshdesk.com/support/discussions/topics/6000059068 | Support thread about retrofitting JuiceBox hardware with OpenEVSE controller | Yes |
| 7d5 | Arduino EVSE Pilot Signal ADC (Arduino Forum) | https://forum.arduino.cc/t/arduino-evse-pilot-signal-adc/1033540 | Technical discussion of reading J1772 pilot signal voltages with ATmega328P ADC | Yes |

---

## Notes

- **All resources listed above are freely accessible** as of February 2026.
- The official SAE J1772 standard document itself is **not free** (available for purchase from SAE International), but the Wikipedia article and OpenEVSE references provide sufficient technical detail for implementation.
- The AMW006 module is a legacy product (acquired by Silicon Labs from Zentri/ACKme); datasheets remain hosted on silabs.com.
- The JuiceBox Gen 1 uses an ATmega328P on an Arduino Pro Mini 5V carrier board, making it firmware-compatible with OpenEVSE which also targets ATmega328P at 16MHz.
- The JuiceRescueController is the most directly relevant project to OpenJuice, as it provides a drop-in OpenEVSE-based replacement board for JuiceBox v1 and v2 hardware.
