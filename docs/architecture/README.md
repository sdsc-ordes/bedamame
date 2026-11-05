# Architecture

For the openBIS administrator.

- [index.html](index.html): the architecture on one page (pipeline, data model, vocabularies, example questions, what is still open). Open it in a browser.
- [changes.md](changes.md): the six proposed changes to the openBIS master data.
- [collaborator-requests.md](collaborator-requests.md): what we need from you.

The ontology, vocabulary and shapes are in [src/ontology/bedretto/](../../src/ontology/bedretto/), and the table from openBIS fields to ontology terms is [src/mapping/openbis-annotations.csv](../../src/mapping/openbis-annotations.csv). The rest of the repository is a minimal implementation that converts openBIS data and checks it; see the main [README](../../README.md).
