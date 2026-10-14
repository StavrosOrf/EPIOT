// Send local calendar dates, never UTC ISO conversions of picker midnights.
export function calendarDate(date) {
  return `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

export function pickerOptions(rangeMode, minDate, today, selectedDates, onChange) {
  const limit = calendarDate(today);
  const valid = selectedDates.filter(date => calendarDate(date) >= calendarDate(minDate) && calendarDate(date) <= limit);
  const dates = valid.length ? valid : [today];
  return {
    mode: rangeMode ? "range" : "single", minDate, maxDate: today,
    dateFormat: "Y-m-d", defaultDate: rangeMode ? [dates[0], dates.at(-1)] : dates.at(-1),
    disableMobile: true, onChange,
  };
}
