# How to Run the Project

## Start the project

1. Install WSL and Docker Desktop on your machine.

2. Open WSL from CMD or Windows Terminal, then change into the directory where this repository is stored.

3. Open the project in VS Code by running:

   code .

4. Open a new terminal in VS Code.

5. Build and start the Docker Compose services by running:

   docker compose up --build -d


## Stop the project

To stop the project, run:

   docker compose down


## Rerun the project cleanly

Before rerunning the project, clean the files from the previous build by running:

   sudo chown -R $USER:$USER shared/outputs shared/data shared/sector_inputs_only
   chmod -R u+rwX shared/outputs shared/data shared/sector_inputs_only
   rm -rf shared/outputs/*
   rm -f shared/data/database.db
   rm -rf shared/sector_inputs_only/*
   rm -f shared/sector_inputs_only.zip

Then start the project again with:

   docker compose up --build -d
