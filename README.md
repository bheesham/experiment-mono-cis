# mono-cis

CIS is made up of many components (various cron jobs and HTTP endpoints).
Python packaging and code distribution has changed since CIS was created.

The cost of large-scale development has been reduced with the introduction of
LLMs. Goals:

1. Preserve existing interfaces and behaviours;
2. Keep existing tests, and add more tests when beneficial;
3. Modernize the parts of CIS which are useful to keep, and plan for the parts
   which will need to be new.

This project aims to modernize CIS, allowing us to make changes in service of
removing large parts. (Deletion _is_ a change.)

Non-goals:

1. New features. The primary goal is to _be able to make changes safely_.
