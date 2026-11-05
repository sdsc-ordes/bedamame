# Requests for the openBIS administrator

We prepare every master-data change in this repository and test it on a local copy of openBIS 7.0.0. You review each change and apply it in production; we never write to production ourselves. To make the local copy match production, we need the following.

## Before anything is applied

1. **The production openBIS version.**
   If production is already 7.x: did the upgrade merge the old `$NAME` with the lab's own `NAME` property? In the 2026-09-23 export they are separate, and BOREHOLE_LOGGING uses `NAME` with the label "Filename" and the naming convention `BH_YYYYMMDD_Tools_Institution_orientation` as its description. In 7.0 they are one property, labelled "Name".
2. **The collection that holds the boreholes.** Their identifiers look like `/INFRASTRUCTURE/BOREHOLES/BFE_D_42`, but no borehole was exported, so we don't know the collection. Locally we use `/INFRASTRUCTURE/BOREHOLES/BOREHOLES`.
3. **Full exports of all 12 Bedretto object types**, including BOREHOLES, made with the "Import Compatible" option: BOREHOLES, BOREHOLE_LOGGING, CORES, CORE_REQUEST, IGSN_CORE, SENSORS, SEIS_SENSOR, SENSOR_INSTAL, SEIS_SENSOR_INSTAL, DATALOGGER, DEVICE, METHOD. So far we have four partial exports (borehole logging, tilt-meter installations, seismic installations, tilt-meter inventory) and one device.
4. **Where the new registers go.** The changes create a space REGISTERS with the collections `/REGISTERS/PEOPLE/PEOPLE_COLLECTION`, `/REGISTERS/ORGANIZATIONS/ORGANIZATIONS_COLLECTION` and `/REGISTERS/TESTBEDS/TESTBEDS_COLLECTION`, and put borehole mouth surveys in `/INFRASTRUCTURE/BOREHOLES/BOREHOLE_MOUTH_SURVEYS`. Tell us if you prefer other places. REGISTERS should be marked as an Inventory space in the ELN settings.
5. **How we may read production data.** Our converter reads objects through the openBIS API (read-only). Either a personal access token for a read-only account, or you run the export command yourself and send us the file. Your choice.

## Every time you apply a change

6. **A fresh master-data export just before each import.** An import with "Update if exists" overwrites labels, sections and descriptions with what is in the file. If the file was built from an old export, it would undo edits made in production since then. We regenerate the change from your fresh export.
7. **Permission to import validation scripts.** openBIS 7.0 lets only the `system` user create or change validation scripts unless `code-plugins.allowed-editing-users` in the application server's `service.properties` lists more users. The lab's CORES type has a validation script, and change 05 carries it unchanged.
8. **The people review sheets.** Changes 01, 03 and 04 create PERSON objects from names typed as free text (split at commas and "and"). Each comes with a review sheet of the names as written. Please correct names and point out duplicates before importing.

## Please check

9. **Tilt meter LY1066.** The installation `BFE_C_23_TILT_2` (FEAR-2) records serial number LY1066, but the inventory has no such sensor. Inventory sensor TILT2 has serial LY1166. Is LY1066 a typo for LY1166? Locally we created a placeholder sensor for LY1066.
10. **BFE_D_31 and tilt meter TILT4.** The borehole list gives BFE_D_31 a length of 12 m, the completion "Open" and the remark "Technical failure, abandoned". The installation `BFE_D_31_TILT1_4` puts tilt meter TILT4 in it at 14 m. Is TILT4 in BFE_D_31, at what depth, and is the borehole open or abandoned? (The archive sheet of the borehole list gives BFE_D_31 as 50 m long, nicknamed FEAR2_perpendicular1.)
11. **Staked-out dates after drilling.** In `borehole_mouth_coord.csv`, 75 positions marked "staked out" are dated after drilling of their borehole started. For example, BFE_C_16 to BFE_C_23 started drilling on 14 to 21 January 2024 and were staked out on 19 to 26 May 2024; BFE_D_41 to BFE_D_67 all started on 4 September 2024 and were staked out in February and March 2025; the BFE_A boreholes were drilled in 2022 and staked out on 18 January 2024. Were some of these positions measured after drilling, and are the dates right? Several rise by one day per borehole, as if filled down in a spreadsheet.
12. **The sign of the dip.** Every row of `borehole_mouth_coord.csv` states the convention "negative downward; positive upward", but the values follow the opposite one: all 41 boreholes described as "Inclined Downward" have a positive dip, all 23 "Inclined Upward" ones a negative dip, and the 30 vertical ones, into which sensors were lowered, +90. Is positive downward, and should the convention text change?
13. **Bug report for openBIS support (optional).** The RO-Crate export of openBIS 7.0.0 fails for 11 of the 12 Bedretto types. It fails on any DATE value, on the property labels "Project" and "Experiment", and on multi-line text properties without a widget setting. We don't depend on it any more, but the lab may want it fixed for its own exports.
14. **The CORES validation script (optional).** CORES uses the ELN's date-range check, which compares START_DATE and END_DATE. CORES has neither field, so the check never runs. A check on the depths would fit:

    ```python
    def getRenderedProperty(entity, property):
        value = entity.property(property)
        if value is not None:
            return value.renderedValue()

    def validate(entity, isNew):
        top = getRenderedProperty(entity, "CORES.TOP")
        bottom = getRenderedProperty(entity, "CORES.BOTTOM")
        if top and bottom and float(top) > float(bottom):
            return "Top depth cannot be below bottom depth!"
    ```
