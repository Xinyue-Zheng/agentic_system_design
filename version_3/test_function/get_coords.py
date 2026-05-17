import pandas as pd

df = pd.read_csv('data/usid_attributes.csv')
print(df.columns.tolist())
usids = ['USID_01', 'USID_25', 'USID_43', 'USID_29', 'USID_45', 'USID_10', 'USID_09']
rows = df[df['USID'].isin(usids)]
print(rows.to_string(index=False))
