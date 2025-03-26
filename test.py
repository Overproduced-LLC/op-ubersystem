from datetime import datetime
arrival_date = datetime.strptime('2025-01-01', '%Y-%m-%d')
departure_date = datetime.strptime('2025-01-03', '%Y-%m-%d')
nights = (departure_date - arrival_date).days
print(nights)