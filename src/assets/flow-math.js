// Shared by the collector, Worker and browser so eligibility and gap handling agree.
export function fundStartDate(fund) {
  return fund.listed_date && fund.listed_date > fund.inception_date ? fund.listed_date : fund.inception_date;
}
export function strictCumulative(values) {
  let sum=0,missing=false;
  return values.map(value=>{
    if(value===null||value===undefined||value===''||!Number.isFinite(Number(value)))missing=true;
    if(missing)return null;
    sum+=Number(value);return sum;
  });
}
export function cumulativeExcess(amount, reference) {
  const valid=v=>v!==null&&v!==undefined&&v!==''&&Number.isFinite(Number(v));
  return strictCumulative(amount.map((value,i)=>valid(value)&&valid(reference[i])?Number(value)-Number(reference[i]):null));
}
export function cumulativeWindow(dates,totals) {
  const valid=v=>v!==null&&v!==undefined&&v!==''&&Number.isFinite(Number(v));
  const missingDates=dates.filter((d,i)=>!valid(totals[i]));
  const firstMissing=totals.findIndex(v=>!valid(v));
  let last=totals.length-1;
  while(last>=0&&!valid(totals[last]))last--;
  let first=last;
  while(first>0&&valid(totals[first-1]))first--;
  return {values:strictCumulative(totals),completeDays:dates.length-missingDates.length,missingDays:missingDates.length,missingDates,firstMissingDate:firstMissing<0?null:dates[firstMissing],cumulativeThrough:firstMissing===0?null:dates[firstMissing<0?dates.length-1:firstMissing-1]??null,lastCompleteRange:last<0?null:{start:dates[first],end:dates[last]}};
}
export const FLOW_ISSUE_LABELS={
  listing_baseline_missing:'上市首日前一份额基准未取得',
  nav_missing:'单位净值缺失或无效',
  share_missing:'当期份额记录未取得',
  previous_share_missing:'前一期份额记录未取得',
  share_change_review:'份额与净值异常变动需核对',
  source_missing:'日度记录未取得'
};
