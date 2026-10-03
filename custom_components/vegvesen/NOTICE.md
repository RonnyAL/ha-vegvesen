# License and data attribution

This integration is based on [ludeeus/integration_blueprint](https://github.com/ludeeus/integration_blueprint).
The included `LICENSE` preserves the scaffold's MIT license and Joakim Sørensen's copyright notice.

**Data provided by Statens vegvesen / Data levert av Statens vegvesen.**

Source data has separate NLOD licensing and attribution requirements:

- [Weather data catalogue](https://dataut.vegvesen.no/nb/dataservice/vaerdata-malinger-api)
- [Road camera catalogue](https://dataut.vegvesen.no/en/dataset/webkamera)
- [DATEX publication documentation](https://www.vegvesen.no/en/fag/technology/open-data/a-selection-of-open-data/what-is-datex/publications/)
- [Road-routing dataset (NLOD)](https://dataut.vegvesen.no/nb/dataset/ruteplandata-bil)

Road-condition forecasts are provided by Statens vegvesen's
[Vegvær map service](https://www.vegvesen.no/fag/teknologi/apne-data/et-utvalg-apne-data/ogc-karttjenester/kartlag/).
The published material inspected did not establish a separate licence statement
for the road-segment forecast collection. Its public availability is not treated
as evidence of a different licence; provider attribution is retained.

**Administrative geography: © Kartverket.** County and municipality names,
codes, bounds and coordinate lookups come from Kartverket's
[administrative units API](https://api.kartverket.no/kommuneinfo/v1/).
These data are licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/),
subject to [Kartverket's terms of use](https://www.kartverket.no/api-og-data/vilkar-for-bruk).
The bundled source index uses point lookups to establish administrative
membership. Runtime selection matches source IDs and coordinates to that index.

The generic road/weather icon is original integration artwork, covered by the project's MIT license. It is not Statens vegvesen's official logo.
