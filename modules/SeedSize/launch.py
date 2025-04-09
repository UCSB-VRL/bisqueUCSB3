#!/usr/bin/env python
import sys
from source.bqcore.bq.engine.controllers.module_run import ModuleRunner
if __name__ == "__main__":
    sys.exit(ModuleRunner().main())
