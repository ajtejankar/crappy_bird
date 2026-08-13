Previously, making payment was the effort while playing the game just pure fun, but now we're tying up effort and playing the game together.
The reward in both cases is the ability to *suggest* modifications (have a say in the game evolution).
Now, I earlier I was too focused on the part of disentangling game playing skills with love for the game itself.
However, all we need to do is following: 

1. at any point in time, only a single version of the game can be played 
2. anyone suggesting how the game should evolve must first at least play it (effort) 
3. each game end state where the number of pipes cleared is greater than > 10 gets a single effort unit (vote) 
4. the vote can be spent in three ways 
    a. upvoting a particular version of the game 
    b. adding a new idea into the idea pile 
    c. upvoting an existing idea 
5. at every game end the votes are used in a 3 node baysian probability network: 
    a. root node has 3 actions: do nothing, go to rollback node, go to idea node (0.5, 0.30, 0.20 default so that idea generation is only 20% of all game plays but configurable) 
    b. rollback node: create a prob dist function based on votes (keep it simple) 
    c. idea node: same as above 
    d. we need to discuss what prob dist functions we can use 
    e. we need to show this process to the players and we need to make it interesting (let's think of some ideas later but for now we can show a spinning wheel with appropriate region occupations to the prob weights) 
    f. the idea and rollback node prob dist functions need to weight the popularity higher but also give random new versions a chance. 
6. now for this idea to work. we need to show game versions prominently 
7. we also need to communicate that the idea implementation is underway, basically show what's happening, (for now since the repo is public we can just put a link to the action run) also gives full transparency 
8. remember all the deletions you had mentioned. we should do those. think carefully about what exactly this new world looks like and ruthlessly delete anything that doesn't agree with it. some core thins like serving the html, 100kb limit etc are the same but a lot of the concepts have changed. 
9. this design makes the whole game unpredictable but also fun and controlling the game evolution becomes more central and engaging.

The end goal however, is the central idea that the whole game is an RL environment for the agent.  
All aspects of the game, the prob weights, the in-game condition of when to give the vote to the user, etc. should eventually be configurable by the agent.
The agent can optimize for evening out its own load so that it doesn't hit usage limits.

- Environment: the game + its player population
- State: the metrics dossier (what players did this week)
- Action space: one release per week, bounded by CONTRACT.md and the verifier
- Reward: usage — deaths, retries, returning players, participation in the evolution
- Memory: the changelog and transcripts — no weights ever update; the agent "learns" purely through artifacts it wrote to itself last week

However, some of these ideas are for later.
