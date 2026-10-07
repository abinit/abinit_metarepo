# Contracts

One file per interface between ABINIT and abipy, `contracts/<topic>.md`, e.g. a new netCDF variable written by
ABINIT and parsed by abipy. Each contract states:

- **Owner:** the repo that produces the data.
- **Consumers:** the repos and modules that read it.
- **Format:** names, types, shapes, units, and the files they appear in.
- **Status:** draft, implemented in owner, implemented in consumers, merged.
- **Test:** the test in each repo that proves the contract holds.
