# Proposed openBIS changes

Six changes to the master data of the Bedretto object types. Each one adds what the ontology needs and removes nothing: new fields get new codes, and the old fields stay until you retire them.

For each change you get a file to import (`NN-name.xlsx`, or a `.zip` when it carries a validation script) and a note that says what it does to your data. We build each file from a fresh export of your openBIS and test it on a local copy first. You import it in the admin UI with **Tools → Import → All**, **Mode: Update if exists**.

| Change | What it does | Why |
|---|---|---|
| 01 People | Free-text name fields (deployed by, removed by, operated by, requested by, owner) become links to PERSON or ORGANIZATION objects. PERSON gets Email and Affiliation. | A person is recorded once and can be found from every object they worked on. |
| 02 Test beds | The TESTBED vocabulary becomes TESTBED objects, and boreholes link to them. | A test bed can carry a description and other facts. |
| 03 Borehole mouth surveys | New type BOREHOLE_MOUTH_SURVEY: one object per planned, staked-out or measured position of a borehole mouth, with its date, source and surveyor. The positions come from the lab's list `borehole_mouth_coord.csv`. | A new survey no longer overwrites the old position. |
| 04 Sensor positions | New type SENSOR_POSITION, linked to the installation. None of the exported installations has coordinates yet, so it starts empty. | A sensor can get a new position without losing the old one. |
| 05 Object links | Installations, logging runs and cores link to their borehole, and installations to their sensor, instead of naming them as text. | A link cannot be misspelt, and openBIS can follow it both ways. |
| 06 Vocabularies | Free-text fields with a fixed set of values, and the yes/no installation fields, become vocabulary fields. The terms come from the Bedretto vocabulary. | Each value is spelt one way and can be searched. |

Changes 01, 03 and 04 create PERSON objects from names typed as text. Each comes with a review sheet of the names as written; see request 8 in [collaborator-requests.md](collaborator-requests.md).
