from dataclasses import dataclass
from pathlib import Path
import pandas as pd


@dataclass
class Battery:
    capacity_kwh: float
    soc: float
    max_charge_kw: float
    max_discharge_kw: float
    eff: float
    soc_max: float
    soc_min: float

    @classmethod
    def from_csv(cls, h_id: str, csv_path: str | Path = "household_params.csv"):
        csv_path = Path(csv_path)
        df = pd.read_csv(csv_path, dtype={"h_id": str})

        row = df.loc[df["h_id"] == h_id]
        if row.empty:
            raise ValueError(f"No battery parameter row found for household {h_id} in {csv_path}")

        row = row.iloc[0]

        return cls(
            capacity_kwh=float(row["capacity_kwh"]),
            soc=float(row["initial_soc"]),
            max_charge_kw=float(row["max_charge_kw"]),
            max_discharge_kw=float(row["max_discharge_kw"]),
            eff=float(row["eff"]),
            soc_max=float(row["soc_max"]),
            soc_min=float(row["soc_min"]),
        )

    def stored_energy(self) -> float:
        return self.soc * self.capacity_kwh

    def charge(self, power: float, t_h: float) -> float:
        power = min(max(power, 0.0), self.max_charge_kw)

        current_energy = self.stored_energy()
        max_allowed = self.soc_max * self.capacity_kwh
        room_left = max_allowed - current_energy

        if room_left <= 0.0:
            return 0.0

        energy_in = power * t_h
        max_input = room_left / self.eff
        actual_input = min(energy_in, max_input)
        actual_stored = actual_input * self.eff

        self.soc += actual_stored / self.capacity_kwh
        self.soc = min(self.soc, self.soc_max)

        return actual_input

    def discharge(self, power: float, t_h: float) -> float:
        power = min(max(power, 0.0), self.max_discharge_kw)

        current_energy = self.stored_energy()
        min_allowed = self.soc_min * self.capacity_kwh
        available_energy = current_energy - min_allowed

        if available_energy <= 0.0:
            return 0.0

        demand_energy = power * t_h
        max_output = available_energy * self.eff
        actual_output = min(demand_energy, max_output)
        actual_taken = actual_output / self.eff

        self.soc -= actual_taken / self.capacity_kwh
        self.soc = max(self.soc, self.soc_min)

        return actual_output