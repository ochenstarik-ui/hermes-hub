const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = vm.createContext({document:{addEventListener(){}},console});
vm.runInContext(fs.readFileSync('src/antigravity_provider/router/web/static/workflow.js','utf8'),context);
const nodes=[{x:430,y:60,width:250,height:116},...Array.from({length:12},(_,i)=>({x:70+i%3*360,y:250+Math.floor(i/3)*240,width:250,height:116}))];
const edges=[[0,1,0],[1,2,0],[2,1,0],[2,3,0],[3,2,1],[3,0,0]];
for(const [source,target,lane] of edges){
  const route=context.workflowEdgeRoute(nodes[source],nodes[target],lane);
  for(let i=1;i<route.points.length;i++){
    const a=route.points[i-1],b=route.points[i];
    assert(a.x===b.x||a.y===b.y,'Routes use orthogonal segments');
    for(const n of nodes){
      const crosses=a.x===b.x
        ? a.x>n.x&&a.x<n.x+n.width&&Math.max(a.y,b.y)>n.y&&Math.min(a.y,b.y)<n.y+n.height
        : a.y>n.y&&a.y<n.y+n.height&&Math.max(a.x,b.x)>n.x&&Math.min(a.x,b.x)<n.x+n.width;
      assert(!crosses,`Route ${source}->${target} crosses a card`);
    }
  }
  assert(!context.roundedWorkflowPath(route.points).includes('NaN'));
}
const down=context.workflowEdgeRoute(nodes[0],nodes[1]);
assert.equal(down.points[0].x,nodes[0].x+nodes[0].width/2);
assert.equal(down.points.at(-1).y,nodes[1].y-7);
const feedback=context.workflowEdgeRoute(nodes[2],nodes[1]);
assert(feedback.points[1].y>nodes[2].y+nodes[2].height);
console.log('A48 routes: downward ports, separate feedback lanes, six routes avoid all 13 cards');
