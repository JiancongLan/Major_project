from battery import Battery


class Household:
    def __init__(
        self,
        h_id: str,
        battery: Battery,
        battery_charge_fraction_from_surplus: float = 1.0,
    ):
        self.h_id = h_id
        self.battery = battery
        self.battery_charge_fraction_from_surplus = float(battery_charge_fraction_from_surplus)

    def _compute_soc_policy(self, future_energy_signal_kwh: float | None) -> tuple[float, float]:
        """
        Returns:
            reserve_soc: minimum SOC to protect when deficit is expected
            charge_cap_soc: temporary upper charge target to preserve headroom when surplus is expected
        """
        base_reserve = max(self.battery.soc_min, 0.50)
        reserve_soc = base_reserve
        charge_cap_soc = self.battery.soc_max

        if future_energy_signal_kwh is None:
            return reserve_soc, charge_cap_soc

        cap = max(self.battery.capacity_kwh, 1e-6)
        signal_ratio = future_energy_signal_kwh / cap

        # Deficit expected: keep more battery reserve
        if signal_ratio >= 0.35:
            reserve_soc = min(self.battery.soc_max - 0.05, 0.80)
            charge_cap_soc = self.battery.soc_max
        elif signal_ratio >= 0.15:
            reserve_soc = min(self.battery.soc_max - 0.05, 0.68)
            charge_cap_soc = self.battery.soc_max

        # Strong surplus expected: preserve headroom so later PV can still be stored
        elif signal_ratio <= -0.35:
            reserve_soc = max(self.battery.soc_min, 0.35)
            charge_cap_soc = min(self.battery.soc_max, 0.58)
        elif signal_ratio <= -0.15:
            reserve_soc = max(self.battery.soc_min, 0.42)
            charge_cap_soc = min(self.battery.soc_max, 0.70)

        return reserve_soc, charge_cap_soc

    def run_slot(
        self,
        demand: float,
        pv: float,
        t_h: float,
        future_energy_signal_kwh: float | None = None,
    ) -> dict:
        energy_before = demand - pv
        battery_charged = 0.0
        battery_discharged = 0.0

        reserve_soc, charge_cap_soc = self._compute_soc_policy(future_energy_signal_kwh)

        if energy_before > 0:
            # Need energy now, but do not discharge below reserve SOC
            old_soc_min = self.battery.soc_min
            self.battery.soc_min = max(self.battery.soc_min, reserve_soc)

            power = energy_before / t_h
            battery_discharged = self.battery.discharge(power, t_h)

            self.battery.soc_min = old_soc_min

        elif energy_before < 0:
            # Surplus now, but preserve battery headroom if more PV is expected soon
            surplus = abs(energy_before)
            surplus_for_battery = surplus * self.battery_charge_fraction_from_surplus

            old_soc_max = self.battery.soc_max
            self.battery.soc_max = min(self.battery.soc_max, charge_cap_soc)

            power = surplus_for_battery / t_h
            battery_charged = self.battery.charge(power, t_h)

            self.battery.soc_max = old_soc_max

        energy_after = demand - pv - battery_discharged + battery_charged

        import_energy = max(0.0, energy_after)
        export_energy = max(0.0, -energy_after)

        return {
            "h_id": self.h_id,
            "demand": demand,
            "pv": pv,
            "battery_charged": battery_charged,
            "battery_discharged": battery_discharged,
            "energy_before": energy_before,
            "energy_after": energy_after,
            "import_energy": import_energy,
            "export_energy": export_energy,
            "soc": self.battery.soc,
            "future_energy_signal_kwh": future_energy_signal_kwh,
            "reserve_soc": reserve_soc,
            "charge_cap_soc": charge_cap_soc,
        }