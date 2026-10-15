# Requests for the openBIS administrator

We prepare every master-data change in this repository and test it on a local copy of openBIS 7.0.0. You review each change and apply it in production; we never write to production ourselves. To make the local copy match production, we need the following.

## Before anything is applied

1. **The production openBIS version**, and whether the RO-Crate server runs there (`/ro-crate-server/`).
   If production is already 7.x: did the upgrade merge the old `$NAME` with the lab's own `NAME` property? In the 2026-09-23 export they are separate, and BOREHOLE_LOGGING uses `NAME` with the label "Filename" and the naming convention `BH_YYYYMMDD_Tools_Institution_orientation` as its description. In 7.0 they are one property, labelled "Name".
2. **The collection that holds the boreholes.** Their identifiers look like `/INFRASTRUCTURE/BOREHOLES/BFE_D_42`, but no borehole was exported, so we don't know the collection. Locally we use `/INFRASTRUCTURE/BOREHOLES/BOREHOLES`.
3. **Full exports of all 12 Bedretto object types**, including BOREHOLES, made with the "Import Compatible" option: BOREHOLES, BOREHOLE_LOGGING, CORES, CORE_REQUEST, IGSN_CORE, SENSORS, SEIS_SENSOR, SENSOR_INSTAL, SEIS_SENSOR_INSTAL, DATALOGGER, DEVICE, METHOD. So far we have four partial exports (borehole logging, tilt-meter installations, seismic installations, tilt-meter inventory) and one device.
4. **Where the new registers go.** The changes create a space REGISTERS with the collections `/REGISTERS/PEOPLE/PEOPLE_COLLECTION`, `/REGISTERS/ORGANIZATIONS/ORGANIZATIONS_COLLECTION` and `/REGISTERS/TESTBEDS/TESTBEDS_COLLECTION`, and put borehole mouth surveys in `/INFRASTRUCTURE/BOREHOLES/BOREHOLE_MOUTH_SURVEYS`. Tell us if you prefer other places. REGISTERS should be marked as an Inventory space in the ELN settings.
5. **How we may read production data.** Our converter reads objects through the openBIS API (read-only). Either a personal access token for a read-only account, or you run the export command yourself and send us the file. Your choice.

## Every time you apply a change

6. **A fresh master-data export just before each import.** An import with "Update if exists" overwrites labels, sections and descriptions with what is in the file. If the file was built from an old export, it would undo edits made in production since then. We regenerate the change from your fresh export.
7. **Permission to import validation scripts.** openBIS 7.0 lets only the `system` user create or change validation scripts unless `code-plugins.allowed-editing-users` in the application server's `service.properties` lists more users. The lab's CORES type has a validation script: change 05 carries it unchanged, and change 07 replaces it.
8. **The people review sheets.** Changes 01, 03 and 04 create PERSON objects from names typed as free text (split at commas and "and"). Each comes with a review sheet of the names as written. Please correct names and point out duplicates before importing.

## Please check

9. **Tilt meter LY1066.** The installation `BFE_C_23_TILT_2` (FEAR-2) records serial number LY1066, but the inventory has no such sensor. Inventory sensor TILT2 has serial LY1166. Is LY1066 a typo for LY1166? Locally we created a placeholder sensor for LY1066.
10. **Bug report for openBIS support (optional).** The RO-Crate export of openBIS 7.0.0 fails for 11 of the 12 Bedretto types. It fails on any DATE value, on the property labels "Project" and "Experiment", and on multi-line text properties without a widget setting. Details are in `README.md` under "RO-Crate export". We don't depend on it any more, but the lab may want it fixed for its own exports.
